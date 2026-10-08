using BCrypt.Net;
using Google.Apis.Auth;
using Microsoft.Extensions.Configuration;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Identity.Auth;
using SystemService.BLL.Services.Identity.Interfaces;
using SystemService.BLL.Services.Payment.Interfaces;
using SystemService.DAL.Entities.Identity;
using SystemService.DAL.Repositories.Identity.Interfaces;
using SystemService.DAL.Repositories.Payment.Interfaces;

namespace SystemService.BLL.Services.Identity.Implementations
{
    public class AuthService : IAuthService
    {
        private readonly IUserRepository _userRepository;
        private readonly IRoleRepository _roleRepository;
        private readonly IRefreshTokenRepository _refreshTokenRepository;
        private readonly ITokenService _tokenService;
        private readonly IOtpService _otpService;
        private readonly IConfiguration _configuration;
        private readonly IWalletRepository _walletRepository;
        private readonly IRewardService _rewardService;

        public AuthService(
            IUserRepository userRepository,
            IRoleRepository roleRepository,
            IRefreshTokenRepository refreshTokenRepository,
            ITokenService tokenService,
            IOtpService otpService,
            IConfiguration configuration,
            IWalletRepository walletRepository,
            IRewardService rewardService)
        {
            _userRepository = userRepository;
            _roleRepository = roleRepository;
            _refreshTokenRepository = refreshTokenRepository;
            _tokenService = tokenService;
            _otpService = otpService;
            _configuration = configuration;
            _walletRepository = walletRepository;
            _rewardService = rewardService;
        }

        public async Task<ApiResponse<object>> RegisterAsync(RegisterRequest request, CancellationToken cancellationToken = default)
        {
            var normalizedEmail = request.Email.Trim().ToLowerInvariant();

            if (await _userRepository.EmailExistsAsync(normalizedEmail, cancellationToken))
            {
                return ApiResponse<object>.FailureResponse("Email is already registered.");
            }

            var defaultRole = await _roleRepository.GetByNameAsync("Member", cancellationToken);
            if (defaultRole == null)
            {
                throw new InvalidOperationException("Default role 'Member' is missing in the database configuration.");
            }

            var passwordHash = BCrypt.Net.BCrypt.HashPassword(request.Password);

            var user = new User
            {
                FullName = request.FullName.Trim(),
                Email = normalizedEmail,
                PasswordHash = passwordHash,
                IsActive = true,
                IsEmailVerified = false,
                CreatedAt = DateTime.UtcNow
            };

            user.UserRoles.Add(new UserRole
            {
                Role = defaultRole,
                AssignedAt = DateTime.UtcNow
            });

            await _userRepository.AddAsync(user, cancellationToken);

            await _otpService.SendOtpAsync(normalizedEmail, "Registration", cancellationToken);

            return ApiResponse<object>.SuccessResponse(new { }, "Registration successful. Please verify the OTP sent to your email.");
        }

        public async Task<ApiResponse<object>> VerifyRegisterOtpAsync(VerifyRegisterOtpRequest request, CancellationToken cancellationToken = default)
        {
            var normalizedEmail = request.Email.Trim().ToLowerInvariant();

            var user = await _userRepository.GetByEmailAsync(normalizedEmail, cancellationToken);
            if (user == null)
            {
                return ApiResponse<object>.FailureResponse("User not found.");
            }

            if (user.IsEmailVerified)
            {
                return ApiResponse<object>.FailureResponse("Email is already verified.");
            }

            var isOtpValid = await _otpService.ValidateAndConsumeOtpAsync(normalizedEmail, request.OtpCode.Trim(), "Registration", cancellationToken);
            if (!isOtpValid)
            {
                return ApiResponse<object>.FailureResponse("Invalid or expired OTP code.");
            }

            user.IsEmailVerified = true;
            user.UpdatedAt = DateTime.UtcNow;

            await _userRepository.UpdateAsync(user, cancellationToken);
            await _walletRepository.GetOrCreateWalletByUserIdAsync(user.UserId, cancellationToken);
            await _rewardService.ClaimFirstLoginRewardAsync(user.UserId, cancellationToken);

            return ApiResponse<object>.SuccessResponse(new { }, "Email verified successfully.");
        }

        public async Task<ApiResponse<LoginResponse>> LoginAsync(LoginRequest request, CancellationToken cancellationToken = default)
        {
            var normalizedEmail = request.Email.Trim().ToLowerInvariant();

            var user = await _userRepository.GetByEmailAsync(normalizedEmail, cancellationToken);
            if (user == null)
            {
                return ApiResponse<LoginResponse>.FailureResponse("Invalid email or password.");
            }

            if (!user.IsActive)
            {
                return ApiResponse<LoginResponse>.FailureResponse("User account is inactive. Please contact support.");
            }

            if (!user.IsEmailVerified)
            {
                return ApiResponse<LoginResponse>.FailureResponse("Email is not verified. Please verify your email with OTP.");
            }

            if (string.IsNullOrEmpty(user.PasswordHash) || !BCrypt.Net.BCrypt.Verify(request.Password, user.PasswordHash))
            {
                return ApiResponse<LoginResponse>.FailureResponse("Invalid email or password.");
            }

            await _walletRepository.GetOrCreateWalletByUserIdAsync(user.UserId, cancellationToken);
            await _rewardService.ClaimFirstLoginRewardAsync(user.UserId, cancellationToken);

            var userWithRoles = await _userRepository.GetUserWithRolesAsync(user.UserId, cancellationToken);
            var roles = userWithRoles?.UserRoles.Select(ur => ur.Role.RoleName).ToList() ?? new List<string>();

            var (token, expiresAt) = _tokenService.GenerateToken(user, roles);
            var (refreshToken, refreshTokenExpiresAt) = _tokenService.GenerateRefreshToken();

            await _refreshTokenRepository.AddAsync(new RefreshToken
            {
                UserId = user.UserId,
                Token = refreshToken,
                ExpiresAt = refreshTokenExpiresAt,
                CreatedAt = DateTime.UtcNow
            }, cancellationToken);

            var response = new LoginResponse
            {
                AccessToken = token,
                ExpiresAt = expiresAt,
                RefreshToken = refreshToken,
                RefreshTokenExpiresAt = refreshTokenExpiresAt,
                User = new UserInfoDto
                {
                    UserId = user.UserId,
                    FullName = user.FullName,
                    Email = user.Email,
                    Roles = roles
                }
            };

            return ApiResponse<LoginResponse>.SuccessResponse(response, "Login successful.");
        }

        public async Task<ApiResponse<LoginResponse>> GoogleLoginAsync(GoogleLoginRequest request, CancellationToken cancellationToken = default)
        {
            GoogleJsonWebSignature.Payload payload;
            try
            {
                var googleClientId = _configuration["GoogleAuth:ClientId"];
                var settings = new GoogleJsonWebSignature.ValidationSettings();
                if (!string.IsNullOrWhiteSpace(googleClientId) && !googleClientId.StartsWith("YOUR_GOOGLE_CLIENT_ID"))
                {
                    settings.Audience = new[] { googleClientId };
                }

                payload = await GoogleJsonWebSignature.ValidateAsync(request.IdToken, settings);
            }
            catch (Exception ex)
            {
                return ApiResponse<LoginResponse>.FailureResponse($"Invalid Google token: {ex.Message}");
            }

            if (string.IsNullOrWhiteSpace(payload.Email))
            {
                return ApiResponse<LoginResponse>.FailureResponse("Unable to retrieve email from Google token.");
            }

            var normalizedEmail = payload.Email.Trim().ToLowerInvariant();
            var user = await _userRepository.GetByEmailAsync(normalizedEmail, cancellationToken);

            if (user == null)
            {
                var defaultRole = await _roleRepository.GetByNameAsync("Member", cancellationToken);
                if (defaultRole == null)
                {
                    throw new InvalidOperationException("Default role 'Member' is missing in the database configuration.");
                }

                user = new User
                {
                    FullName = string.IsNullOrWhiteSpace(payload.Name) ? normalizedEmail.Split('@')[0] : payload.Name.Trim(),
                    Email = normalizedEmail,
                    PasswordHash = null,
                    AvatarUrl = payload.Picture,
                    IsEmailVerified = true,
                    IsActive = true,
                    CreatedAt = DateTime.UtcNow
                };

                user.UserRoles.Add(new UserRole
                {
                    Role = defaultRole,
                    AssignedAt = DateTime.UtcNow
                });

                await _userRepository.AddAsync(user, cancellationToken);
            }
            else if (!user.IsActive)
            {
                return ApiResponse<LoginResponse>.FailureResponse("User account is inactive. Please contact support.");
            }
            else if (string.IsNullOrWhiteSpace(user.AvatarUrl) && !string.IsNullOrWhiteSpace(payload.Picture))
            {
                user.AvatarUrl = payload.Picture;
                user.UpdatedAt = DateTime.UtcNow;
                await _userRepository.UpdateAsync(user, cancellationToken);
            }

            await _walletRepository.GetOrCreateWalletByUserIdAsync(user.UserId, cancellationToken);
            await _rewardService.ClaimFirstLoginRewardAsync(user.UserId, cancellationToken);

            var userWithRoles = await _userRepository.GetUserWithRolesAsync(user.UserId, cancellationToken);
            var roles = userWithRoles?.UserRoles.Select(ur => ur.Role.RoleName).ToList() ?? new List<string>();

            var (token, expiresAt) = _tokenService.GenerateToken(user, roles);
            var (refreshToken, refreshTokenExpiresAt) = _tokenService.GenerateRefreshToken();

            await _refreshTokenRepository.AddAsync(new RefreshToken
            {
                UserId = user.UserId,
                Token = refreshToken,
                ExpiresAt = refreshTokenExpiresAt,
                CreatedAt = DateTime.UtcNow
            }, cancellationToken);

            var response = new LoginResponse
            {
                AccessToken = token,
                ExpiresAt = expiresAt,
                RefreshToken = refreshToken,
                RefreshTokenExpiresAt = refreshTokenExpiresAt,
                User = new UserInfoDto
                {
                    UserId = user.UserId,
                    FullName = user.FullName,
                    Email = user.Email,
                    Roles = roles
                }
            };

            return ApiResponse<LoginResponse>.SuccessResponse(response, "Google login successful.");
        }

        public async Task<ApiResponse<object>> SendOtpAsync(SendOtpRequest request, CancellationToken cancellationToken = default)
        {
            return await _otpService.SendOtpAsync(request.Email, request.Type, cancellationToken);
        }

        public async Task<ApiResponse<object>> VerifyOtpAsync(VerifyOtpRequest request, CancellationToken cancellationToken = default)
        {
            return await _otpService.VerifyOtpAsync(request.Email, request.Code, request.Type, cancellationToken);
        }

        public async Task<ApiResponse<object>> ResetPasswordAsync(ResetPasswordRequest request, CancellationToken cancellationToken = default)
        {
            var normalizedEmail = request.Email.Trim().ToLowerInvariant();

            var user = await _userRepository.GetByEmailAsync(normalizedEmail, cancellationToken);
            if (user == null)
            {
                return ApiResponse<object>.FailureResponse("User with this email does not exist.");
            }

            var isOtpValid = await _otpService.ValidateAndConsumeOtpAsync(normalizedEmail, request.OtpCode.Trim(), "ForgotPassword", cancellationToken);
            if (!isOtpValid)
            {
                return ApiResponse<object>.FailureResponse("Invalid or expired OTP code.");
            }

            user.PasswordHash = BCrypt.Net.BCrypt.HashPassword(request.NewPassword);
            user.UpdatedAt = DateTime.UtcNow;

            await _userRepository.UpdateAsync(user, cancellationToken);

            return ApiResponse<object>.SuccessResponse(new { }, "Password reset successfully. You can now log in with your new password.");
        }

        public async Task<ApiResponse<object>> ChangePasswordAsync(int userId, ChangePasswordRequest request, CancellationToken cancellationToken = default)
        {
            var user = await _userRepository.GetByIdAsync(userId, cancellationToken);
            if (user == null)
            {
                return ApiResponse<object>.FailureResponse("User not found.");
            }

            if (string.IsNullOrEmpty(user.PasswordHash) || !BCrypt.Net.BCrypt.Verify(request.CurrentPassword, user.PasswordHash))
            {
                return ApiResponse<object>.FailureResponse("Current password is incorrect.");
            }

            user.PasswordHash = BCrypt.Net.BCrypt.HashPassword(request.NewPassword);
            user.UpdatedAt = DateTime.UtcNow;

            await _userRepository.UpdateAsync(user, cancellationToken);

            return ApiResponse<object>.SuccessResponse(new { }, "Password changed successfully.");
        }

        public async Task<ApiResponse<LoginResponse>> RefreshTokenAsync(RefreshTokenRequest request, CancellationToken cancellationToken = default)
        {
            var storedToken = await _refreshTokenRepository.GetByTokenAsync(request.RefreshToken.Trim(), cancellationToken);
            if (storedToken == null)
            {
                return ApiResponse<LoginResponse>.FailureResponse("Invalid refresh token.");
            }

            if (storedToken.IsRevoked)
            {
                return ApiResponse<LoginResponse>.FailureResponse("Refresh token has been revoked.");
            }

            if (storedToken.ExpiresAt <= DateTime.UtcNow)
            {
                return ApiResponse<LoginResponse>.FailureResponse("Refresh token has expired. Please log in again.");
            }

            var user = storedToken.User;
            if (user == null)
            {
                user = await _userRepository.GetByIdAsync(storedToken.UserId, cancellationToken);
            }

            if (user == null || !user.IsActive)
            {
                return ApiResponse<LoginResponse>.FailureResponse("User account is inactive or not found.");
            }

            var userWithRoles = await _userRepository.GetUserWithRolesAsync(user.UserId, cancellationToken);
            var roles = userWithRoles?.UserRoles.Select(ur => ur.Role.RoleName).ToList() ?? new List<string>();

            var (newAccessToken, accessExpiresAt) = _tokenService.GenerateToken(user, roles);
            var (newRefreshToken, refreshExpiresAt) = _tokenService.GenerateRefreshToken();

            // Revoke old token and rotate
            storedToken.IsRevoked = true;
            storedToken.ReplacedByToken = newRefreshToken;
            await _refreshTokenRepository.UpdateAsync(storedToken, cancellationToken);

            // Add new refresh token
            await _refreshTokenRepository.AddAsync(new RefreshToken
            {
                UserId = user.UserId,
                Token = newRefreshToken,
                ExpiresAt = refreshExpiresAt,
                CreatedAt = DateTime.UtcNow
            }, cancellationToken);

            var response = new LoginResponse
            {
                AccessToken = newAccessToken,
                ExpiresAt = accessExpiresAt,
                RefreshToken = newRefreshToken,
                RefreshTokenExpiresAt = refreshExpiresAt,
                User = new UserInfoDto
                {
                    UserId = user.UserId,
                    FullName = user.FullName,
                    Email = user.Email,
                    Roles = roles
                }
            };

            return ApiResponse<LoginResponse>.SuccessResponse(response, "Token refreshed successfully.");
        }

        public async Task<ApiResponse<object>> RevokeTokenAsync(string token, CancellationToken cancellationToken = default)
        {
            var storedToken = await _refreshTokenRepository.GetByTokenAsync(token.Trim(), cancellationToken);
            if (storedToken == null)
            {
                return ApiResponse<object>.FailureResponse("Token not found.");
            }

            if (storedToken.IsRevoked)
            {
                return ApiResponse<object>.SuccessResponse(new { }, "Token is already revoked.");
            }

            storedToken.IsRevoked = true;
            await _refreshTokenRepository.UpdateAsync(storedToken, cancellationToken);

            return ApiResponse<object>.SuccessResponse(new { }, "Token revoked successfully.");
        }
    }
}

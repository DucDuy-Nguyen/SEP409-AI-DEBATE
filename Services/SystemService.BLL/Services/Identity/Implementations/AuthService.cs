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
using SystemService.DAL.Entities.Identity;
using SystemService.DAL.Repositories.Identity.Interfaces;

namespace SystemService.BLL.Services.Identity.Implementations
{
    public class AuthService : IAuthService
    {
        private readonly IUserRepository _userRepository;
        private readonly IRoleRepository _roleRepository;
        private readonly ITokenService _tokenService;
        private readonly IOtpService _otpService;
        private readonly IConfiguration _configuration;

        public AuthService(
            IUserRepository userRepository,
            IRoleRepository roleRepository,
            ITokenService tokenService,
            IOtpService otpService,
            IConfiguration configuration)
        {
            _userRepository = userRepository;
            _roleRepository = roleRepository;
            _tokenService = tokenService;
            _otpService = otpService;
            _configuration = configuration;
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

            var userWithRoles = await _userRepository.GetUserWithRolesAsync(user.UserId, cancellationToken);
            var roles = userWithRoles?.UserRoles.Select(ur => ur.Role.RoleName).ToList() ?? new List<string>();

            var (token, expiresAt) = _tokenService.GenerateToken(user, roles);

            var response = new LoginResponse
            {
                AccessToken = token,
                ExpiresAt = expiresAt,
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

            var userWithRoles = await _userRepository.GetUserWithRolesAsync(user.UserId, cancellationToken);
            var roles = userWithRoles?.UserRoles.Select(ur => ur.Role.RoleName).ToList() ?? new List<string>();

            var (token, expiresAt) = _tokenService.GenerateToken(user, roles);

            var response = new LoginResponse
            {
                AccessToken = token,
                ExpiresAt = expiresAt,
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
    }
}

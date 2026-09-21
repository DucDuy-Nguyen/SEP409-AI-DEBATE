using BCrypt.Net;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using SystemService.Common.Responses;
using SystemService.Models.DTOs.Identity.Auth;
using SystemService.Models.Entities.Identity;
using SystemService.Repositories.Identity.Interfaces;
using SystemService.Services.Identity.Interfaces;

namespace SystemService.Services.Identity.Implementations
{
    public class AuthService : IAuthService
    {
        private readonly IUserRepository _userRepository;
        private readonly IRoleRepository _roleRepository;
        private readonly ITokenService _tokenService;

        public AuthService(
            IUserRepository userRepository,
            IRoleRepository roleRepository,
            ITokenService tokenService)
        {
            _userRepository = userRepository;
            _roleRepository = roleRepository;
            _tokenService = tokenService;
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

            return ApiResponse<object>.SuccessResponse(new { }, "Registration successful.");
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

            if (!BCrypt.Net.BCrypt.Verify(request.Password, user.PasswordHash))
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

        public async Task<ApiResponse<object>> ChangePasswordAsync(int userId, ChangePasswordRequest request, CancellationToken cancellationToken = default)
        {
            var user = await _userRepository.GetByIdAsync(userId, cancellationToken);
            if (user == null)
            {
                return ApiResponse<object>.FailureResponse("User not found.");
            }

            if (!BCrypt.Net.BCrypt.Verify(request.CurrentPassword, user.PasswordHash))
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

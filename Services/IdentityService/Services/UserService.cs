using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using IdentityService.DTOs.Users;
using IdentityService.Models;
using IdentityService.Repositories.Interfaces;
using IdentityService.Services.Interfaces;

namespace IdentityService.Services
{
    public class UserService : IUserService
    {
        private readonly IUserRepository _userRepository;

        public UserService(IUserRepository userRepository)
        {
            _userRepository = userRepository;
        }

        public async Task<UserResponse> GetUserProfileAsync(int userId)
        {
            var user = await _userRepository.GetByIdAsync(userId);
            if (user == null)
            {
                throw new KeyNotFoundException($"User with ID {userId} not found.");
            }

            return MapToUserResponse(user);
        }

        public async Task<UserResponse> UpdateUserProfileAsync(int userId, UpdateProfileRequest request)
        {
            var user = await _userRepository.GetByIdAsync(userId);
            if (user == null)
            {
                throw new KeyNotFoundException($"User with ID {userId} not found.");
            }

            if (!string.IsNullOrWhiteSpace(request.FullName))
            {
                user.FullName = request.FullName;
            }
            if (request.AvatarUrl != null)
            {
                user.AvatarUrl = request.AvatarUrl;
            }
            if (request.DateOfBirth.HasValue)
            {
                user.DateOfBirth = request.DateOfBirth;
            }
            if (!string.IsNullOrWhiteSpace(request.Gender))
            {
                user.Gender = request.Gender;
            }
            if (request.PhoneNumber != null)
            {
                user.PhoneNumber = request.PhoneNumber;
            }

            user.UpdatedAt = DateTime.UtcNow;

            await _userRepository.UpdateUserAsync(user);
            await _userRepository.SaveChangesAsync();

            return MapToUserResponse(user);
        }

        public async Task<(List<UserResponse> Users, int TotalCount)> GetUsersPagedAsync(int page, int pageSize)
        {
            if (page < 1) page = 1;
            if (pageSize < 1) pageSize = 10;

            var (users, totalCount) = await _userRepository.GetUsersPagedAsync(page, pageSize);
            var responses = users.Select(MapToUserResponse).ToList();
            return (responses, totalCount);
        }

        public async Task<UserResponse> GetUserByIdAsync(int userId)
        {
            var user = await _userRepository.GetByIdAsync(userId);
            if (user == null)
            {
                throw new KeyNotFoundException($"User with ID {userId} not found.");
            }

            return MapToUserResponse(user);
        }

        public async Task<UserResponse> UpdateUserStatusAsync(int userId, UpdateUserStatusRequest request)
        {
            var user = await _userRepository.GetByIdAsync(userId);
            if (user == null)
            {
                throw new KeyNotFoundException($"User with ID {userId} not found.");
            }

            user.IsActive = request.IsActive;
            user.UpdatedAt = DateTime.UtcNow;

            await _userRepository.UpdateUserAsync(user);
            await _userRepository.SaveChangesAsync();

            return MapToUserResponse(user);
        }

        public async Task<UserResponse> UpdateUserRolesAsync(int userId, UpdateUserRoleRequest request)
        {
            var user = await _userRepository.GetByIdAsync(userId);
            if (user == null)
            {
                throw new KeyNotFoundException($"User with ID {userId} not found.");
            }

            // Distinct roles to prevent duplicates
            var requestedRoleNames = request.Roles.Distinct().ToList();
            var validRoles = await _userRepository.GetRolesByNamesAsync(requestedRoleNames);

            if (validRoles.Count != requestedRoleNames.Count)
            {
                var foundNames = validRoles.Select(r => r.RoleName);
                var invalidNames = requestedRoleNames.Except(foundNames);
                throw new InvalidOperationException($"Invalid role(s): {string.Join(", ", invalidNames)}");
            }

            // Remove existing user roles and assign new ones
            await _userRepository.RemoveUserRolesAsync(userId);
            await _userRepository.SaveChangesAsync();

            foreach (var role in validRoles)
            {
                await _userRepository.AddUserRoleAsync(new UserRole
                {
                    UserId = userId,
                    RoleId = role.RoleId,
                    AssignedAt = DateTime.UtcNow
                });
            }

            await _userRepository.SaveChangesAsync();

            var updatedUser = await _userRepository.GetByIdAsync(userId);
            return MapToUserResponse(updatedUser ?? user);
        }

        private static UserResponse MapToUserResponse(User user)
        {
            var roles = user.UserRoles?.Select(ur => ur.Role?.RoleName ?? string.Empty).Where(r => !string.IsNullOrEmpty(r)).ToList()
                        ?? new List<string>();

            return new UserResponse
            {
                UserId = user.UserId,
                FullName = user.FullName,
                Email = user.Email,
                AvatarUrl = user.AvatarUrl,
                DateOfBirth = user.DateOfBirth,
                Gender = user.Gender,
                PhoneNumber = user.PhoneNumber,
                IsActive = user.IsActive,
                Roles = roles
            };
        }
    }
}

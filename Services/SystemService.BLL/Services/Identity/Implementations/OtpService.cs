using System;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.Services.Identity.Interfaces;
using SystemService.DAL.Entities.Identity;
using SystemService.DAL.Repositories.Identity.Interfaces;

namespace SystemService.BLL.Services.Identity.Implementations
{
    public class OtpService : IOtpService
    {
        private readonly IOtpRepository _otpRepository;
        private readonly IUserRepository _userRepository;
        private readonly IEmailService _emailService;

        public OtpService(
            IOtpRepository otpRepository,
            IUserRepository userRepository,
            IEmailService emailService)
        {
            _otpRepository = otpRepository;
            _userRepository = userRepository;
            _emailService = emailService;
        }

        public async Task<ApiResponse<object>> SendOtpAsync(string email, string type, CancellationToken cancellationToken = default)
        {
            var normalizedEmail = email.Trim().ToLowerInvariant();
            var normalizedType = type.Trim();

            if (normalizedType.Equals("Registration", StringComparison.OrdinalIgnoreCase))
            {
                var existingUser = await _userRepository.GetByEmailAsync(normalizedEmail, cancellationToken);
                if (existingUser != null && existingUser.IsEmailVerified)
                {
                    return ApiResponse<object>.FailureResponse("Email is already registered and verified.");
                }
            }
            else if (normalizedType.Equals("ForgotPassword", StringComparison.OrdinalIgnoreCase))
            {
                var user = await _userRepository.GetByEmailAsync(normalizedEmail, cancellationToken);
                if (user == null)
                {
                    return ApiResponse<object>.FailureResponse("User with this email does not exist.");
                }
            }
            else
            {
                return ApiResponse<object>.FailureResponse("Invalid OTP type. Allowed types are Registration and ForgotPassword.");
            }

            await _otpRepository.InvalidatePreviousOtpsAsync(normalizedEmail, normalizedType, cancellationToken);

            var code = RandomNumberGenerator.GetInt32(100000, 1000000).ToString("D6");
            var expiresAt = DateTime.UtcNow.AddMinutes(5);

            var otpCode = new OtpCode
            {
                Email = normalizedEmail,
                Code = code,
                Type = normalizedType,
                ExpiresAt = expiresAt,
                IsUsed = false,
                CreatedAt = DateTime.UtcNow
            };

            await _otpRepository.AddAsync(otpCode, cancellationToken);

            var purposeDisplay = normalizedType.Equals("Registration", StringComparison.OrdinalIgnoreCase)
                ? "Đăng ký tài khoản"
                : "Đặt lại mật khẩu";

            await _emailService.SendOtpEmailAsync(normalizedEmail, code, purposeDisplay, cancellationToken);

            return ApiResponse<object>.SuccessResponse(new { }, $"OTP code sent successfully to {normalizedEmail}. Valid for 5 minutes.");
        }

        public async Task<ApiResponse<object>> VerifyOtpAsync(string email, string code, string type, CancellationToken cancellationToken = default)
        {
            var otp = await _otpRepository.GetLatestValidOtpAsync(email, code, type, cancellationToken);
            if (otp == null)
            {
                return ApiResponse<object>.FailureResponse("Invalid or expired OTP code.");
            }

            return ApiResponse<object>.SuccessResponse(new { Verified = true }, "OTP code is valid.");
        }

        public async Task<bool> ValidateAndConsumeOtpAsync(string email, string code, string type, CancellationToken cancellationToken = default)
        {
            var otp = await _otpRepository.GetLatestValidOtpAsync(email, code, type, cancellationToken);
            if (otp == null)
            {
                return false;
            }

            await _otpRepository.MarkAsUsedAsync(otp, cancellationToken);
            return true;
        }
    }
}

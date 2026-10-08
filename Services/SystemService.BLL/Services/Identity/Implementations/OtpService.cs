using System;
using System.Security.Cryptography;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.Services.Identity.Interfaces;
using SystemService.DAL.Repositories.Identity.Interfaces;

namespace SystemService.BLL.Services.Identity.Implementations
{
    public class OtpService : IOtpService
    {
        private readonly IOtpCacheService _otpCacheService;
        private readonly IUserRepository _userRepository;
        private readonly IEmailService _emailService;

        public OtpService(
            IOtpCacheService otpCacheService,
            IUserRepository userRepository,
            IEmailService emailService)
        {
            _otpCacheService = otpCacheService;
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

            var code = RandomNumberGenerator.GetInt32(100000, 1000000).ToString("D6");
            var expiry = TimeSpan.FromMinutes(5);

            // Lưu trực tiếp vào Cache với TTL 5 phút (ghi đè và tự động hủy mã cũ)
            await _otpCacheService.SaveOtpAsync(normalizedEmail, code, normalizedType, expiry, cancellationToken);

            var purposeDisplay = normalizedType.Equals("Registration", StringComparison.OrdinalIgnoreCase)
                ? "Đăng ký tài khoản"
                : "Đặt lại mật khẩu";

            await _emailService.SendOtpEmailAsync(normalizedEmail, code, purposeDisplay, cancellationToken);

            return ApiResponse<object>.SuccessResponse(new { }, $"OTP code sent successfully to {normalizedEmail}. Valid for 5 minutes.");
        }

        public async Task<ApiResponse<object>> VerifyOtpAsync(string email, string code, string type, CancellationToken cancellationToken = default)
        {
            var cachedOtp = await _otpCacheService.GetOtpAsync(email, type, cancellationToken);
            if (cachedOtp == null || !string.Equals(cachedOtp.Code, code.Trim(), StringComparison.Ordinal))
            {
                return ApiResponse<object>.FailureResponse("Invalid or expired OTP code.");
            }

            return ApiResponse<object>.SuccessResponse(new { Verified = true }, "OTP code is valid.");
        }

        public async Task<bool> ValidateAndConsumeOtpAsync(string email, string code, string type, CancellationToken cancellationToken = default)
        {
            var cachedOtp = await _otpCacheService.GetOtpAsync(email, type, cancellationToken);
            if (cachedOtp == null || !string.Equals(cachedOtp.Code, code.Trim(), StringComparison.Ordinal))
            {
                return false;
            }

            // Xóa OTP khỏi cache ngay khi sử dụng để tránh replay
            await _otpCacheService.RemoveOtpAsync(email, type, cancellationToken);
            return true;
        }
    }
}

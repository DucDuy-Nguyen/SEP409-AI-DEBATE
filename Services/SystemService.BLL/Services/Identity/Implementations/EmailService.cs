using MailKit.Net.Smtp;
using MailKit.Security;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Logging;
using MimeKit;
using System;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Services.Identity.Interfaces;

namespace SystemService.BLL.Services.Identity.Implementations
{
    public class EmailService : IEmailService
    {
        private readonly IConfiguration _configuration;
        private readonly ILogger<EmailService> _logger;

        public EmailService(IConfiguration configuration, ILogger<EmailService> logger)
        {
            _configuration = configuration;
            _logger = logger;
        }

        public async Task SendOtpEmailAsync(string toEmail, string otpCode, string purpose, CancellationToken cancellationToken = default)
        {
            var smtpServer = _configuration["EmailSettings:SmtpServer"] ?? "smtp.gmail.com";
            var smtpPort = int.TryParse(_configuration["EmailSettings:SmtpPort"], out int port) ? port : 587;
            var senderEmail = _configuration["EmailSettings:SenderEmail"] ?? "noreply@aidebate.com";
            var senderName = _configuration["EmailSettings:SenderName"] ?? "AI Debate Platform";
            var username = _configuration["EmailSettings:Username"];
            var password = _configuration["EmailSettings:Password"];
            var enableSsl = bool.TryParse(_configuration["EmailSettings:EnableSsl"], out bool ssl) && ssl;

            _logger.LogInformation("==========================================");
            _logger.LogInformation("OTP Code for [{ToEmail}] ({Purpose}): {OtpCode}", toEmail, purpose, otpCode);
            _logger.LogInformation("==========================================");

            if (string.IsNullOrWhiteSpace(username) || string.IsNullOrWhiteSpace(password))
            {
                _logger.LogWarning("SMTP credentials not configured. OTP code logged to console output.");
                return;
            }

            try
            {
                var message = new MimeMessage();
                message.From.Add(new MailboxAddress(senderName, senderEmail));
                message.To.Add(new MailboxAddress("", toEmail));
                message.Subject = $"[{senderName}] Mã xác minh OTP: {otpCode}";

                var bodyBuilder = new BodyBuilder
                {
                    HtmlBody = $@"
                        <div style='font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;'>
                            <h2 style='color: #4f46e5; text-align: center;'>{senderName}</h2>
                            <p>Xin chào,</p>
                            <p>Bạn đã yêu cầu mã xác minh OTP cho mục đích: <strong>{purpose}</strong>.</p>
                            <div style='background-color: #f3f4f6; padding: 15px; text-align: center; font-size: 28px; font-weight: bold; letter-spacing: 5px; color: #1f2937; border-radius: 6px; margin: 20px 0;'>
                                {otpCode}
                            </div>
                            <p>Mã này có hiệu lực trong vòng <strong>5 phút</strong>. Vui lòng không chia sẻ mã này với bất kỳ ai.</p>
                            <p style='margin-top: 30px; font-size: 12px; color: #6b7280; text-align: center;'>Trân trọng,<br/>Đội ngũ {senderName}</p>
                        </div>"
                };

                message.Body = bodyBuilder.ToMessageBody();

                using var client = new SmtpClient();
                var secureSocketOption = enableSsl ? SecureSocketOptions.StartTls : SecureSocketOptions.Auto;
                await client.ConnectAsync(smtpServer, smtpPort, secureSocketOption, cancellationToken);
                await client.AuthenticateAsync(username, password, cancellationToken);
                await client.SendAsync(message, cancellationToken);
                await client.DisconnectAsync(true, cancellationToken);

                _logger.LogInformation("OTP email successfully sent to {ToEmail}", toEmail);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "Failed to send OTP email to {ToEmail}. OTP logged above.", toEmail);
            }
        }
    }
}

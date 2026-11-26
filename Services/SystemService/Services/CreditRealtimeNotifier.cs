using System;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.AspNetCore.SignalR;
using Microsoft.Extensions.Logging;
using SystemService.BLL.Services.Payment.Interfaces;
using SystemService.Hubs;

namespace SystemService.Services
{
    public class CreditRealtimeNotifier : ICreditRealtimeNotifier
    {
        private readonly IHubContext<DebateHub> _hubContext;
        private readonly ILogger<CreditRealtimeNotifier> _logger;

        public CreditRealtimeNotifier(IHubContext<DebateHub> hubContext, ILogger<CreditRealtimeNotifier> logger)
        {
            _hubContext = hubContext;
            _logger = logger;
        }

        public async Task NotifyCreditBalanceUpdatedAsync(
            int userId,
            long balance,
            long previousBalance,
            long amountChanged,
            long? transactionId = null,
            string? referenceId = null,
            string? reason = null,
            CancellationToken cancellationToken = default)
        {
            try
            {
                var payload = new
                {
                    userId = userId,
                    balance = balance,
                    previousBalance = previousBalance,
                    amountChanged = amountChanged,
                    transactionId = transactionId?.ToString() ?? Guid.NewGuid().ToString(),
                    referenceId = referenceId,
                    reason = reason ?? "TRANSACTION",
                    occurredAt = DateTime.UtcNow.ToString("o")
                };

                await _hubContext.Clients.User(userId.ToString()).SendAsync("CreditBalanceUpdated", payload, cancellationToken);
                await _hubContext.Clients.Group($"user_{userId}").SendAsync("CreditBalanceUpdated", payload, cancellationToken);

                _logger.LogInformation("SignalR CreditBalanceUpdated sent to User {UserId}: balance={Balance}, change={AmountChanged}, reason={Reason}",
                    userId, balance, amountChanged, reason);
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Failed to send SignalR CreditBalanceUpdated for User {UserId}", userId);
            }
        }

        public async Task NotifyCreditTransactionCreatedAsync(
            int userId,
            object transactionData,
            CancellationToken cancellationToken = default)
        {
            try
            {
                await _hubContext.Clients.User(userId.ToString()).SendAsync("CreditTransactionCreated", transactionData, cancellationToken);
                await _hubContext.Clients.Group($"user_{userId}").SendAsync("CreditTransactionCreated", transactionData, cancellationToken);
            }
            catch (Exception ex)
            {
                _logger.LogWarning(ex, "Failed to send SignalR CreditTransactionCreated for User {UserId}", userId);
            }
        }
    }
}

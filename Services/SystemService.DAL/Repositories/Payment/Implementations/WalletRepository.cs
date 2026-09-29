using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using SystemService.DAL.Context;
using SystemService.DAL.Entities.Payment;
using SystemService.DAL.Repositories.Payment.Interfaces;

namespace SystemService.DAL.Repositories.Payment.Implementations
{
    public class WalletRepository : IWalletRepository
    {
        private readonly SystemDbContext _context;

        public WalletRepository(SystemDbContext context)
        {
            _context = context;
        }

        public async Task<Wallet?> GetByUserIdAsync(int userId, CancellationToken cancellationToken = default)
        {
            return await _context.Wallets
                .FirstOrDefaultAsync(w => w.UserId == userId, cancellationToken);
        }

        public async Task<Wallet?> GetByIdAsync(int walletId, CancellationToken cancellationToken = default)
        {
            return await _context.Wallets
                .FirstOrDefaultAsync(w => w.WalletId == walletId, cancellationToken);
        }

        public async Task<Wallet?> GetByIdForUpdateAsync(int walletId, CancellationToken cancellationToken = default)
        {
            return await _context.Wallets
                .FromSqlInterpolated($"SELECT * FROM Wallets WITH (UPDLOCK, ROWLOCK) WHERE WalletId = {walletId}")
                .FirstOrDefaultAsync(cancellationToken);
        }

        public async Task<Wallet?> GetByUserIdForUpdateAsync(int userId, CancellationToken cancellationToken = default)
        {
            return await _context.Wallets
                .FromSqlInterpolated($"SELECT * FROM Wallets WITH (UPDLOCK, ROWLOCK) WHERE UserId = {userId}")
                .FirstOrDefaultAsync(cancellationToken);
        }

        public async Task<Wallet> CreateWalletAsync(Wallet wallet, CancellationToken cancellationToken = default)
        {
            await _context.Wallets.AddAsync(wallet, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
            return wallet;
        }

        public async Task<Wallet> GetOrCreateWalletByUserIdAsync(int userId, CancellationToken cancellationToken = default)
        {
            var wallet = await GetByUserIdAsync(userId, cancellationToken);
            if (wallet != null)
            {
                return wallet;
            }

            try
            {
                wallet = new Wallet
                {
                    UserId = userId,
                    Balance = 0,
                    CreatedAt = DateTime.UtcNow
                };
                await _context.Wallets.AddAsync(wallet, cancellationToken);
                await _context.SaveChangesAsync(cancellationToken);
                return wallet;
            }
            catch (DbUpdateException)
            {
                // In case another thread created the wallet simultaneously
                var existing = await GetByUserIdAsync(userId, cancellationToken);
                if (existing != null)
                {
                    return existing;
                }
                throw;
            }
        }

        public async Task UpdateWalletAsync(Wallet wallet, CancellationToken cancellationToken = default)
        {
            _context.Wallets.Update(wallet);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task AddTransactionAsync(WalletTransaction transaction, CancellationToken cancellationToken = default)
        {
            await _context.WalletTransactions.AddAsync(transaction, cancellationToken);
            await _context.SaveChangesAsync(cancellationToken);
        }

        public async Task<(List<WalletTransaction> Items, int TotalCount)> GetTransactionsAsync(int walletId, int page, int pageSize, CancellationToken cancellationToken = default)
        {
            if (page < 1) page = 1;
            if (pageSize < 1) pageSize = 20;

            var query = _context.WalletTransactions
                .Where(wt => wt.WalletId == walletId);

            var totalCount = await query.CountAsync(cancellationToken);

            var items = await query
                .OrderByDescending(wt => wt.CreatedAt)
                .Skip((page - 1) * pageSize)
                .Take(pageSize)
                .ToListAsync(cancellationToken);

            return (items, totalCount);
        }
    }
}

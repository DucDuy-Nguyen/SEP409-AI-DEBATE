using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Logging;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Payment;
using SystemService.BLL.Services.Payment.Interfaces;
using SystemService.DAL.Entities.Payment;
using SystemService.DAL.Repositories.Payment.Interfaces;

namespace SystemService.BLL.Services.Payment.Implementations
{
    public class CreditPackageService : ICreditPackageService
    {
        private readonly ICreditPackageRepository _packageRepository;
        private readonly ILogger<CreditPackageService>? _logger;

        public CreditPackageService(
            ICreditPackageRepository packageRepository,
            ILogger<CreditPackageService>? logger = null)
        {
            _packageRepository = packageRepository;
            _logger = logger;
        }

        public async Task<ApiResponse<List<CreditPackageResponse>>> GetActivePackagesAsync(CancellationToken cancellationToken = default)
        {
            var packages = await _packageRepository.GetActivePackagesAsync(cancellationToken);

            var result = packages.Select(p => new CreditPackageResponse
            {
                PackageId = p.PackageId,
                PackageCode = p.PackageCode,
                PackageName = p.PackageName,
                Price = p.Price,
                Currency = p.Currency,
                CreditAmount = p.CreditAmount,
                BonusCredit = p.BonusCredit
            }).ToList();

            return ApiResponse<List<CreditPackageResponse>>.SuccessResponse(result);
        }

        public async Task<ApiResponse<List<CreditPackageAdminResponse>>> GetAllPackagesAsync(CancellationToken cancellationToken = default)
        {
            var packages = await _packageRepository.GetAllAsync(cancellationToken);
            var result = packages.Select(MapToAdminResponse).ToList();
            return ApiResponse<List<CreditPackageAdminResponse>>.SuccessResponse(result);
        }

        public async Task<ApiResponse<CreditPackageAdminResponse>> CreatePackageAsync(CreateCreditPackageRequest request, CancellationToken cancellationToken = default)
        {
            if (request == null)
            {
                return ApiResponse<CreditPackageAdminResponse>.FailureResponse("Request body cannot be null.");
            }

            if (string.IsNullOrWhiteSpace(request.PackageCode))
            {
                return ApiResponse<CreditPackageAdminResponse>.FailureResponse("PackageCode is required.");
            }
            var packageCode = request.PackageCode.Trim();
            if (packageCode.Length > 50)
            {
                return ApiResponse<CreditPackageAdminResponse>.FailureResponse("PackageCode cannot exceed 50 characters.");
            }

            if (string.IsNullOrWhiteSpace(request.PackageName))
            {
                return ApiResponse<CreditPackageAdminResponse>.FailureResponse("PackageName is required.");
            }
            var packageName = request.PackageName.Trim();
            if (packageName.Length > 100)
            {
                return ApiResponse<CreditPackageAdminResponse>.FailureResponse("PackageName cannot exceed 100 characters.");
            }

            if (request.Price <= 0)
            {
                return ApiResponse<CreditPackageAdminResponse>.FailureResponse("Price must be greater than 0.");
            }

            if (string.IsNullOrWhiteSpace(request.Currency))
            {
                return ApiResponse<CreditPackageAdminResponse>.FailureResponse("Currency is required.");
            }
            var currency = request.Currency.Trim();
            if (currency.Length > 10)
            {
                return ApiResponse<CreditPackageAdminResponse>.FailureResponse("Currency cannot exceed 10 characters.");
            }

            if (request.CreditAmount <= 0)
            {
                return ApiResponse<CreditPackageAdminResponse>.FailureResponse("CreditAmount must be greater than 0.");
            }

            if (request.BonusCredit < 0)
            {
                return ApiResponse<CreditPackageAdminResponse>.FailureResponse("BonusCredit must be greater than or equal to 0.");
            }

            if (await _packageRepository.ExistsByPackageCodeAsync(packageCode, null, cancellationToken))
            {
                return ApiResponse<CreditPackageAdminResponse>.FailureResponse($"Credit package with code '{packageCode}' already exists.");
            }

            var entity = new CreditPackage
            {
                PackageCode = packageCode,
                PackageName = packageName,
                Price = request.Price,
                Currency = currency,
                CreditAmount = request.CreditAmount,
                BonusCredit = request.BonusCredit,
                IsActive = request.IsActive,
                CreatedAt = DateTime.UtcNow,
                UpdatedAt = null
            };

            try
            {
                await _packageRepository.CreateAsync(entity, cancellationToken);
            }
            catch (DbUpdateException ex)
            {
                _logger?.LogError(ex, "Error creating credit package with code {PackageCode}", packageCode);
                return ApiResponse<CreditPackageAdminResponse>.FailureResponse($"Credit package with code '{packageCode}' already exists or violates constraint.");
            }

            return ApiResponse<CreditPackageAdminResponse>.SuccessResponse(MapToAdminResponse(entity), "Credit package created successfully.");
        }

        public async Task<ApiResponse<CreditPackageAdminResponse>> PatchPackageAsync(int packageId, PatchCreditPackageRequest request, CancellationToken cancellationToken = default)
        {
            if (request == null || request.IsEmpty())
            {
                return ApiResponse<CreditPackageAdminResponse>.FailureResponse("Request body cannot be empty.");
            }

            var package = await _packageRepository.GetByIdAsync(packageId, cancellationToken);
            if (package == null)
            {
                return ApiResponse<CreditPackageAdminResponse>.FailureResponse("Credit package not found.");
            }

            if (request.HasPackageCode)
            {
                if (string.IsNullOrWhiteSpace(request.PackageCode))
                {
                    return ApiResponse<CreditPackageAdminResponse>.FailureResponse("PackageCode cannot be empty.");
                }
                var code = request.PackageCode.Trim();
                if (code.Length > 50)
                {
                    return ApiResponse<CreditPackageAdminResponse>.FailureResponse("PackageCode cannot exceed 50 characters.");
                }
                if (await _packageRepository.ExistsByPackageCodeAsync(code, packageId, cancellationToken))
                {
                    return ApiResponse<CreditPackageAdminResponse>.FailureResponse($"Credit package with code '{code}' already exists.");
                }
                package.PackageCode = code;
            }

            if (request.HasPackageName)
            {
                if (string.IsNullOrWhiteSpace(request.PackageName))
                {
                    return ApiResponse<CreditPackageAdminResponse>.FailureResponse("PackageName cannot be empty.");
                }
                var name = request.PackageName.Trim();
                if (name.Length > 100)
                {
                    return ApiResponse<CreditPackageAdminResponse>.FailureResponse("PackageName cannot exceed 100 characters.");
                }
                package.PackageName = name;
            }

            if (request.HasPrice)
            {
                if (!request.Price.HasValue)
                {
                    return ApiResponse<CreditPackageAdminResponse>.FailureResponse("Price cannot be null.");
                }
                if (request.Price.Value <= 0)
                {
                    return ApiResponse<CreditPackageAdminResponse>.FailureResponse("Price must be greater than 0.");
                }
                package.Price = request.Price.Value;
            }

            if (request.HasCurrency)
            {
                if (string.IsNullOrWhiteSpace(request.Currency))
                {
                    return ApiResponse<CreditPackageAdminResponse>.FailureResponse("Currency cannot be empty.");
                }
                var curr = request.Currency.Trim();
                if (curr.Length > 10)
                {
                    return ApiResponse<CreditPackageAdminResponse>.FailureResponse("Currency cannot exceed 10 characters.");
                }
                package.Currency = curr;
            }

            if (request.HasCreditAmount)
            {
                if (!request.CreditAmount.HasValue)
                {
                    return ApiResponse<CreditPackageAdminResponse>.FailureResponse("CreditAmount cannot be null.");
                }
                if (request.CreditAmount.Value <= 0)
                {
                    return ApiResponse<CreditPackageAdminResponse>.FailureResponse("CreditAmount must be greater than 0.");
                }
                package.CreditAmount = request.CreditAmount.Value;
            }

            if (request.HasBonusCredit)
            {
                if (!request.BonusCredit.HasValue)
                {
                    return ApiResponse<CreditPackageAdminResponse>.FailureResponse("BonusCredit cannot be null.");
                }
                if (request.BonusCredit.Value < 0)
                {
                    return ApiResponse<CreditPackageAdminResponse>.FailureResponse("BonusCredit must be greater than or equal to 0.");
                }
                package.BonusCredit = request.BonusCredit.Value;
            }

            if (request.HasIsActive)
            {
                if (!request.IsActive.HasValue)
                {
                    return ApiResponse<CreditPackageAdminResponse>.FailureResponse("IsActive cannot be null.");
                }
                package.IsActive = request.IsActive.Value;
            }

            package.UpdatedAt = DateTime.UtcNow;

            try
            {
                await _packageRepository.UpdateAsync(package, cancellationToken);
            }
            catch (DbUpdateException ex)
            {
                _logger?.LogError(ex, "Error updating credit package {PackageId}", packageId);
                return ApiResponse<CreditPackageAdminResponse>.FailureResponse("Failed to update credit package due to database constraint violation.");
            }

            return ApiResponse<CreditPackageAdminResponse>.SuccessResponse(MapToAdminResponse(package), "Credit package updated successfully.");
        }

        private static CreditPackageAdminResponse MapToAdminResponse(CreditPackage p) => new()
        {
            PackageId = p.PackageId,
            PackageCode = p.PackageCode,
            PackageName = p.PackageName,
            Price = p.Price,
            Currency = p.Currency,
            CreditAmount = p.CreditAmount,
            BonusCredit = p.BonusCredit,
            IsActive = p.IsActive,
            CreatedAt = p.CreatedAt,
            UpdatedAt = p.UpdatedAt
        };
    }
}

using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Payment;
using SystemService.BLL.Services.Payment.Interfaces;

namespace SystemService.Controllers.Payment
{
    [ApiController]
    [Route("api/admin/credit-packages")]
    [Authorize(Roles = "Admin")]
    public class AdminCreditPackagesController : ControllerBase
    {
        private readonly ICreditPackageService _packageService;

        public AdminCreditPackagesController(ICreditPackageService packageService)
        {
            _packageService = packageService;
        }

        [HttpGet]
        public async Task<IActionResult> GetAllPackages(CancellationToken cancellationToken)
        {
            var result = await _packageService.GetAllPackagesAsync(cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [HttpPost]
        public async Task<IActionResult> CreatePackage([FromBody] CreateCreditPackageRequest request, CancellationToken cancellationToken)
        {
            var result = await _packageService.CreatePackageAsync(request, cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }

        [HttpPatch("{packageId:int}")]
        public async Task<IActionResult> PatchPackage(
            [FromRoute] int packageId,
            [FromBody] PatchCreditPackageRequest request,
            CancellationToken cancellationToken)
        {
            var result = await _packageService.PatchPackageAsync(packageId, request, cancellationToken);
            if (!result.Success)
            {
                if (result.Message == "Credit package not found.")
                {
                    return NotFound(result);
                }
                return BadRequest(result);
            }
            return Ok(result);
        }
    }
}

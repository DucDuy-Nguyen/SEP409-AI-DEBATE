using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Payment;
using SystemService.BLL.Services.Payment.Interfaces;

namespace SystemService.Controllers.Payment
{
    [ApiController]
    [Route("api/credit-packages")]
    public class CreditPackagesController : ControllerBase
    {
        private readonly ICreditPackageService _packageService;

        public CreditPackagesController(ICreditPackageService packageService)
        {
            _packageService = packageService;
        }

        [HttpGet]
        public async Task<IActionResult> GetActivePackages(CancellationToken cancellationToken)
        {
            var result = await _packageService.GetActivePackagesAsync(cancellationToken);
            if (!result.Success)
            {
                return BadRequest(result);
            }
            return Ok(result);
        }
    }
}

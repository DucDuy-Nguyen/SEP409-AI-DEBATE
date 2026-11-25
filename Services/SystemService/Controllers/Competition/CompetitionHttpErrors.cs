using Microsoft.AspNetCore.Mvc;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.Services.Competition;

namespace SystemService.Controllers.Competition
{
    internal static class CompetitionHttpErrors
    {
        internal static IActionResult Map<T>(ControllerBase controller, ApiResponse<T> response)
        {
            if (response.Errors is InsufficientCreditsErrorDetail insufficient)
            {
                return controller.BadRequest(new ApiResponse<InsufficientCreditsData>
                {
                    Success = false,
                    Code = InsufficientCreditsErrorDetail.ErrorCode,
                    Message = response.Message,
                    Data = new InsufficientCreditsData
                    {
                        RequiredCredits = insufficient.RequiredCredits,
                        CurrentCredits = insufficient.CurrentCredits,
                        MissingCredits = insufficient.MissingCredits
                    },
                    Errors = insufficient
                });
            }

            return response.Errors switch
            {
                CompetitionErrorCodes.Forbidden => controller.StatusCode(403, response),
                CompetitionErrorCodes.NotFound => controller.NotFound(response),
                CompetitionErrorCodes.Conflict => controller.Conflict(response),
                _ => controller.BadRequest(response)
            };
        }
    }
}

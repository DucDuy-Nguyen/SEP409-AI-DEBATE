using System.Collections.Generic;
using System.Threading;
using System.Threading.Tasks;
using SystemService.BLL.Common.Responses;
using SystemService.BLL.DTOs.Identity.Users;

namespace SystemService.BLL.Services.Identity.Interfaces
{
    public interface IFeaturedLearnerService
    {
        Task<ApiResponse<List<FeaturedLearnerDto>>> GetFeaturedLearnersAsync(FeaturedLearnersQuery query, CancellationToken cancellationToken = default);
    }
}

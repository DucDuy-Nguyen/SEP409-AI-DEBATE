using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.BLL.DTOs.Debate
{
    public class JoinSessionRequest
    {
        public DebateSide? PreferredSide { get; set; }
    }
}

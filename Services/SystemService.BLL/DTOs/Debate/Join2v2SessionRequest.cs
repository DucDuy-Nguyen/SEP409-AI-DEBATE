using System.ComponentModel.DataAnnotations;
using SystemService.DAL.Entities.Debate.Enums;

namespace SystemService.BLL.DTOs.Debate
{
    public class Join2v2SessionRequest
    {
        public DebateSide? PreferredSide { get; set; }
    }
}

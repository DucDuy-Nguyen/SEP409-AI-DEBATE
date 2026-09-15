using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;

namespace IdentityService.DTOs.Users
{
    public class UpdateUserRoleRequest
    {
        [Required(ErrorMessage = "Roles list is required.")]
        public List<string> Roles { get; set; } = new List<string>();
    }
}

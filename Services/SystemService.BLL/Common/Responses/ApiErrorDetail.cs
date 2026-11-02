namespace SystemService.BLL.Common.Responses
{
    public class ApiErrorDetail
    {
        public string Code { get; set; } = null!;

        public ApiErrorDetail() { }

        public ApiErrorDetail(string code)
        {
            Code = code;
        }
    }
}

using System;
using System.Text.Json.Serialization;

namespace SystemService.BLL.Common.Responses
{
    public class ApiResponse<T>
    {
        public bool Success { get; set; }

        [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
        public string? Code { get; set; }

        public string Message { get; set; } = string.Empty;
        public T? Data { get; set; }
        public object? Errors { get; set; }

        public ApiResponse() { }

        public ApiResponse(bool success, string message, T? data = default, object? errors = null, string? code = null)
        {
            Success = success;
            Message = message;
            Data = data;
            Errors = errors;
            Code = code;
        }

        public static ApiResponse<T> SuccessResponse(T data, string message = "Success")
        {
            return new ApiResponse<T>(true, message, data);
        }

        public static ApiResponse<T> FailureResponse(string message, object? errors = null)
        {
            return new ApiResponse<T>(false, message, default, errors);
        }

        public static ApiResponse<T> FailureWithCode(string message, string code, object? errors = null)
        {
            return new ApiResponse<T>(false, message, default, errors ?? new ApiErrorDetail(code), code);
        }

        public static ApiResponse<T> InsufficientCreditsResponse(
            long requiredCredits,
            long currentCredits,
            string message = "Không đủ Credit để sử dụng chức năng này")
        {
            var detail = new InsufficientCreditsErrorDetail(requiredCredits, currentCredits);
            T? data = default;
            if (typeof(T) == typeof(object) || typeof(T) == typeof(InsufficientCreditsData))
            {
                data = (T)(object)new InsufficientCreditsData
                {
                    RequiredCredits = detail.RequiredCredits,
                    CurrentCredits = detail.CurrentCredits,
                    MissingCredits = detail.MissingCredits
                };
            }

            return new ApiResponse<T>(false, message, data, detail, InsufficientCreditsErrorDetail.ErrorCode);
        }
    }

    public class InsufficientCreditsData
    {
        public long RequiredCredits { get; set; }
        public long CurrentCredits { get; set; }
        public long MissingCredits { get; set; }
    }

    public class InsufficientCreditsErrorDetail : ApiErrorDetail
    {
        public const string ErrorCode = "INSUFFICIENT_CREDITS";

        public long RequiredCredits { get; set; }
        public long CurrentCredits { get; set; }
        public long MissingCredits { get; set; }

        public InsufficientCreditsErrorDetail(long requiredCredits, long currentCredits)
            : base(ErrorCode)
        {
            RequiredCredits = requiredCredits;
            CurrentCredits = currentCredits;
            MissingCredits = Math.Max(0, requiredCredits - currentCredits);
        }
    }
}

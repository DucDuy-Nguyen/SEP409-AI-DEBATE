using System;
using System.Collections.Generic;
using System.Net;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Extensions.Logging.Abstractions;
using SystemService.BLL.Common.Debate;
using SystemService.BLL.DTOs.KnowledgeBase;
using SystemService.BLL.Services.KnowledgeBase.Implementations;
using Xunit;

namespace SystemService.Tests.Debate
{
    public class KnowledgeBaseServiceTests
    {
        private sealed class FakeHttpMessageHandler : HttpMessageHandler
        {
            public HttpRequestMessage? LastRequest { get; private set; }
            public string? LastBody { get; private set; }
            public HttpStatusCode StatusToReturn { get; set; } = HttpStatusCode.OK;
            public string ResponseBody { get; set; } = "{}";

            protected override async Task<HttpResponseMessage> SendAsync(
                HttpRequestMessage request, CancellationToken cancellationToken)
            {
                LastRequest = request;
                LastBody = request.Content != null
                    ? await request.Content.ReadAsStringAsync(cancellationToken)
                    : null;
                return new HttpResponseMessage(StatusToReturn)
                {
                    Content = new StringContent(ResponseBody, Encoding.UTF8, "application/json")
                };
            }
        }

        private sealed class FakeFactory : IHttpClientFactory
        {
            private readonly HttpClient _client;
            public FakeFactory(HttpMessageHandler handler)
            {
                _client = new HttpClient(handler) { BaseAddress = new Uri("http://localhost:8000/") };
            }
            public HttpClient CreateClient(string name) => _client;
        }

        [Fact]
        public async Task CreateSource_RejectsInvalidTopic_WithoutCallingEvaluator()
        {
            var handler = new FakeHttpMessageHandler();
            var svc = new KnowledgeBaseService(new FakeFactory(handler), NullLogger<KnowledgeBaseService>.Instance);

            var (code, body) = await svc.CreateSourceAsync(new CreateKnowledgeSourceRequest
            {
                Topic = "General",
                RawText = "Some fact"
            });

            Assert.Equal(400, code);
            Assert.False(body.Success);
            Assert.Equal(TopicCategories.InvalidMessage, body.Message);
            Assert.Null(handler.LastRequest);
        }

        [Fact]
        public async Task CreateSource_NormalizesVietnameseTopic_AndForwardsToEvaluator()
        {
            var handler = new FakeHttpMessageHandler
            {
                StatusToReturn = HttpStatusCode.Created,
                ResponseBody = "{\"source_id\":\"11111111-1111-1111-1111-111111111111\",\"created_facts\":1}"
            };
            var svc = new KnowledgeBaseService(new FakeFactory(handler), NullLogger<KnowledgeBaseService>.Instance);

            var (code, body) = await svc.CreateSourceAsync(new CreateKnowledgeSourceRequest
            {
                Topic = "Giáo dục",
                Title = "Bao cao",
                RawText = "Ty le biet chu dat 95%."
            });

            Assert.Equal(201, code);
            Assert.True(body.Success);
            Assert.Equal("http://localhost:8000/rag/knowledge-base/sources", handler.LastRequest!.RequestUri!.ToString());
            Assert.Contains("\"topic\":\"education\"", handler.LastBody);
        }

        [Fact]
        public async Task UpdateFactStatus_RejectsUnknownStatus()
        {
            var handler = new FakeHttpMessageHandler();
            var svc = new KnowledgeBaseService(new FakeFactory(handler), NullLogger<KnowledgeBaseService>.Instance);

            var (code, body) = await svc.UpdateFactStatusAsync(
                Guid.NewGuid(),
                new UpdateFactStatusRequest { Status = "invalid_status" });

            Assert.Equal(400, code);
            Assert.False(body.Success);
            Assert.Null(handler.LastRequest);
        }

        [Fact]
        public async Task BatchUpdateStatus_ForwardsApprovedStatus()
        {
            var handler = new FakeHttpMessageHandler
            {
                StatusToReturn = HttpStatusCode.OK,
                ResponseBody = "{\"updated_count\":2,\"status\":\"approved\"}"
            };
            var svc = new KnowledgeBaseService(new FakeFactory(handler), NullLogger<KnowledgeBaseService>.Instance);

            var (code, body) = await svc.BatchUpdateFactStatusAsync(new BatchUpdateFactStatusRequest
            {
                FactIds = new List<Guid> { Guid.NewGuid(), Guid.NewGuid() },
                Status = "APPROVED"
            });

            Assert.Equal(200, code);
            Assert.True(body.Success);
            Assert.Equal("http://localhost:8000/rag/knowledge-base/facts/batch-status", handler.LastRequest!.RequestUri!.ToString());
            Assert.Contains("\"status\":\"approved\"", handler.LastBody);
        }
    }
}


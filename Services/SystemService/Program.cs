using SystemService.HostedServices;
using SystemService.Hubs;
using SystemService.Services;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Builder;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.IdentityModel.Tokens;
using Microsoft.OpenApi.Models;
using System;
using System.Text;

using SystemService.BLL.Services.Competition.Implementations;
using SystemService.BLL.Services.Competition.Interfaces;
using SystemService.BLL.Services.Debate.Implementations;
using SystemService.BLL.Services.Debate.Interfaces;
using SystemService.BLL.Services.Identity.Implementations;
using SystemService.BLL.Services.Identity.Interfaces;
using SystemService.BLL.Services.KnowledgeBase.Implementations;
using SystemService.BLL.Services.KnowledgeBase.Interfaces;

using SystemService.DAL.Context;
using SystemService.DAL.Repositories.Competition.Implementations;
using SystemService.DAL.Repositories.Competition.Interfaces;
using SystemService.DAL.Repositories.Debate.Implementations;
using SystemService.DAL.Repositories.Debate.Interfaces;
using SystemService.DAL.Repositories.Identity.Implementations;
using SystemService.DAL.Repositories.Identity.Interfaces;
using SystemService.DAL.Repositories.Payment.Implementations;
using SystemService.DAL.Repositories.Payment.Interfaces;

using SystemService.BLL.Services.AI.Implementations;
using SystemService.BLL.Services.AI.Interfaces;
using SystemService.BLL.Services.Payment.Implementations;
using SystemService.BLL.Services.Payment.Interfaces;

using SystemService.Middleware;

var builder = WebApplication.CreateBuilder(args);

// 1. Controllers
builder.Services.AddControllers();

// 2. DbContext
// Real values never live in appsettings.json (public repo): user-secrets on a dev machine, environment variables
// (ConnectionStrings__DefaultConnection) on a server, see docs/SECRETS.md. A Development run falls back to the local
// SQL Server; anywhere else a missing value stops the start instead of failing on the first query.
var connectionString = builder.Configuration.GetConnectionString("DefaultConnection");
if (string.IsNullOrWhiteSpace(connectionString))
{
    if (!builder.Environment.IsDevelopment())
    {
        throw new InvalidOperationException(
            "ConnectionStrings:DefaultConnection is not configured (set the ConnectionStrings__DefaultConnection environment variable).");
    }
    connectionString = "Server=localhost;Database=DebatePracticePlatformDB;Trusted_Connection=True;TrustServerCertificate=True";
}
builder.Services.AddDbContext<SystemDbContext>(options =>
    options.UseSqlServer(connectionString));

// 3. Cache & Distributed Cache
var redisConnectionString = builder.Configuration.GetConnectionString("Redis");
if (!string.IsNullOrWhiteSpace(redisConnectionString))
{
    builder.Services.AddStackExchangeRedisCache(options =>
    {
        options.Configuration = redisConnectionString;
        options.InstanceName = "AIDebate_";
    });
}
else
{
    builder.Services.AddDistributedMemoryCache();
}
builder.Services.AddSingleton<IOtpCacheService, OtpCacheService>();

// 4. Repositories (Identity, Competition & Debate)
builder.Services.AddScoped<IUserRepository, UserRepository>();
builder.Services.AddScoped<IRoleRepository, RoleRepository>();
builder.Services.AddScoped<IRefreshTokenRepository, RefreshTokenRepository>();

builder.Services.AddScoped<ICompetitionRepository, CompetitionRepository>();
builder.Services.AddScoped<ICompetitionRegistrationRepository, CompetitionRegistrationRepository>();
builder.Services.AddScoped<ICompetitionTeamRepository, CompetitionTeamRepository>();
builder.Services.AddScoped<ICompetitionTeamRequestRepository, CompetitionTeamRequestRepository>();
builder.Services.AddScoped<ICompetitionJudgeRepository, CompetitionJudgeRepository>();
builder.Services.AddScoped<IDebateFormatRepository, DebateFormatRepository>();

builder.Services.AddScoped<IWalletRepository, WalletRepository>();
builder.Services.AddScoped<ICreditPackageRepository, CreditPackageRepository>();
builder.Services.AddScoped<IPaymentRepository, PaymentRepository>();
builder.Services.AddScoped<IRewardRepository, RewardRepository>();

builder.Services.AddScoped<IDebateRepository, DebateRepository>();
builder.Services.AddScoped<IDebateChallengeRepository, DebateChallengeRepository>();
builder.Services.AddScoped<ITopicRepository, TopicRepository>();

builder.Services.AddScoped<ITokenService, TokenService>();
builder.Services.AddScoped<IEmailService, EmailService>();
builder.Services.AddScoped<IOtpService, OtpService>();
builder.Services.AddScoped<IAuthService, AuthService>();
builder.Services.AddScoped<IUserService, UserService>();
builder.Services.AddScoped<IFeaturedLearnerService, FeaturedLearnerService>();
builder.Services.AddScoped<IAdminService, AdminService>();

builder.Services.AddScoped<ICompetitionService, CompetitionService>();
builder.Services.AddScoped<ICompetitionRegistrationService, CompetitionRegistrationService>();
builder.Services.AddScoped<ICompetitionTeamService, CompetitionTeamService>();
builder.Services.AddScoped<ICompetitionTeamRequestService, CompetitionTeamRequestService>();
builder.Services.AddScoped<ICompetitionJudgeService, CompetitionJudgeService>();
builder.Services.AddScoped<ICompetitionDebateBridgeService, CompetitionDebateBridgeService>();
builder.Services.AddScoped<ICompetitionTournamentService, CompetitionTournamentService>();

builder.Services.AddScoped<IPaymentGateway, PayOSPaymentGateway>();
builder.Services.AddScoped<IWalletService, WalletService>();
builder.Services.AddScoped<ICreditPackageService, CreditPackageService>();
builder.Services.AddScoped<IPaymentService, PaymentService>();
builder.Services.AddScoped<IRewardService, RewardService>();
builder.Services.AddScoped<ICreditService, CreditService>();

// Singleton: one evaluation per debate session at a time, shared by every request (DebateService is scoped)
builder.Services.AddSingleton<DebateEvaluationCoordinator>();
builder.Services.AddSignalR();
builder.Services.AddScoped<IDebateRealtimeNotifier, DebateRealtimeNotifier>();
builder.Services.AddScoped<IDebateService, DebateService>();
// Team call (2v2, preparation minute): STUN / Cloudflare TURN (TeamCall:Cloudflare:TurnKeyId / TurnKeyApiToken)
builder.Services.AddHttpClient<IIceServerProvider, CloudflareIceServerProvider>(client =>
{
    client.Timeout = TimeSpan.FromSeconds(10);
});
builder.Services.AddScoped<ITeamCallService, TeamCallService>();
builder.Services.AddScoped<IDebateChallengeService, DebateChallengeService>();
builder.Services.AddScoped<ITopicService, TopicService>();
builder.Services.AddScoped<IKnowledgeBaseService, KnowledgeBaseService>();

// 5. AI Services Clients
// An empty value (as appsettings.json ships them) means "not set", like a missing one: `??` alone would keep "" and
// every call would then fail on an invalid base address
static string OrDefault(string? value, string fallback) => string.IsNullOrWhiteSpace(value) ? fallback : value;
var evaluatorUrl = OrDefault(builder.Configuration["AiServices:EvaluatorUrl"],
    "https://adpp-ai-evaluator.greenstone-4d67d46a.indonesiacentral.azurecontainerapps.io");
var opponentUrl = OrDefault(builder.Configuration["AiServices:OpponentUrl"], "http://localhost:8002");
var aiTimeoutSeconds = builder.Configuration.GetValue<int>("AiServices:TimeoutSeconds", 120);

builder.Services.AddHttpClient<IAiEvaluatorClient, AiEvaluatorClient>(client =>
{
    client.BaseAddress = new Uri(evaluatorUrl.TrimEnd('/') + "/");
    client.Timeout = TimeSpan.FromSeconds(aiTimeoutSeconds);
});

builder.Services.AddHttpClient<IAiOpponentClient, AiOpponentClient>(client =>
{
    client.BaseAddress = new Uri(opponentUrl.TrimEnd('/') + "/");
    client.Timeout = TimeSpan.FromSeconds(aiTimeoutSeconds);
});

// Warm-up after startup (background, never blocks it): EF query of the evaluation + AI Evaluator /health/ready
builder.Services.AddHttpClient(StartupWarmupService.EvaluatorHttpClientName, client =>
{
    client.BaseAddress = new Uri(evaluatorUrl.TrimEnd('/') + "/");
    client.Timeout = TimeSpan.FromSeconds(30);
});
builder.Services.AddHttpClient(KnowledgeBaseService.EvaluatorKbClientName, client =>
{
    client.BaseAddress = new Uri(evaluatorUrl.TrimEnd('/') + "/");
    client.Timeout = TimeSpan.FromSeconds(60);
});
builder.Services.AddHostedService<StartupWarmupService>();

// 6. Authentication & JWT
const string DevelopmentJwtKey = "development-secret-key-super-secret-1234567890";
var configuredJwtKey = builder.Configuration["Jwt:Key"];
// The fallback key is in the public repo (as are older keys in its history): anyone could sign a token with it, so
// only a Development run may use it. Elsewhere the key must be set, private, and long enough for HMAC-SHA256.
if (!builder.Environment.IsDevelopment())
{
    if (string.IsNullOrWhiteSpace(configuredJwtKey))
    {
        throw new InvalidOperationException("Jwt:Key is not configured (set the Jwt__Key environment variable).");
    }
    if (configuredJwtKey == DevelopmentJwtKey || System.Text.Encoding.UTF8.GetByteCount(configuredJwtKey) < 32)
    {
        throw new InvalidOperationException("Jwt:Key must be a private key of at least 32 bytes, not the development key.");
    }
}
var jwtKey = string.IsNullOrWhiteSpace(configuredJwtKey) ? DevelopmentJwtKey : configuredJwtKey!;
// TokenService signs with Jwt:Key: give it the same key the validation below uses, an empty one fails every login
builder.Configuration["Jwt:Key"] = jwtKey;
var jwtIssuer = builder.Configuration["Jwt:Issuer"] ?? "AIDebatePlatform";
var jwtAudience = builder.Configuration["Jwt:Audience"] ?? "AIDebatePlatform";

builder.Services.AddAuthentication(options =>
{
    options.DefaultAuthenticateScheme = JwtBearerDefaults.AuthenticationScheme;
    options.DefaultChallengeScheme = JwtBearerDefaults.AuthenticationScheme;
})
.AddJwtBearer(options =>
{
    options.TokenValidationParameters = new TokenValidationParameters
    {
        ValidateIssuer = true,
        ValidateAudience = true,
        ValidateLifetime = true,
        ValidateIssuerSigningKey = true,
        ValidIssuer = jwtIssuer,
        ValidAudience = jwtAudience,
        IssuerSigningKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(jwtKey)),
        ClockSkew = TimeSpan.Zero
    };
    options.Events = new JwtBearerEvents
    {
        OnMessageReceived = context =>
        {
            var accessToken = context.Request.Query["access_token"];
            var path = context.HttpContext.Request.Path;
            if (!string.IsNullOrEmpty(accessToken) && path.StartsWithSegments("/hubs"))
            {
                context.Token = accessToken;
            }
            return Task.CompletedTask;
        }
    };
});

builder.Services.AddAuthorization();

// 7. Swagger
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(c =>
{
    c.SwaggerDoc("v1", new OpenApiInfo
    {
        Title = "System Service API - AI Debate Practice Platform",
        Version = "v1",
        Description = "Central Business Service handling Identity, Competition & Debate Modules."
    });

    c.AddSecurityDefinition("Bearer", new OpenApiSecurityScheme
    {
        Description = "JWT Authorization header using the Bearer scheme. Enter 'Bearer' [space] and then your token in the text input below.\r\n\r\nExample: \"Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...\"",
        Name = "Authorization",
        In = ParameterLocation.Header,
        Type = SecuritySchemeType.ApiKey,
        Scheme = "Bearer"
    });

    c.AddSecurityRequirement(new OpenApiSecurityRequirement
    {
        {
            new OpenApiSecurityScheme
            {
                Reference = new OpenApiReference
                {
                    Type = ReferenceType.SecurityScheme,
                    Id = "Bearer"
                }
            },
            Array.Empty<string>()
        }
    });
});

var app = builder.Build();

// Middleware pipeline
app.UseMiddleware<ExceptionMiddleware>();

if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI(c =>
    {
        c.SwaggerEndpoint("/swagger/v1/swagger.json", "System Service API v1");
    });
}

app.UseAuthentication();
app.UseAuthorization();

app.MapControllers();
app.MapHub<DebateHub>("/hubs/debate");

app.Run();

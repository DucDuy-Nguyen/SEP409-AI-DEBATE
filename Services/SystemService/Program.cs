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
using SystemService.BLL.Services.Identity.Implementations;
using SystemService.BLL.Services.Identity.Interfaces;

using SystemService.DAL.Context;
using SystemService.DAL.Repositories.Competition.Implementations;
using SystemService.DAL.Repositories.Competition.Interfaces;
using SystemService.DAL.Repositories.Identity.Implementations;
using SystemService.DAL.Repositories.Identity.Interfaces;

using SystemService.Middleware;

var builder = WebApplication.CreateBuilder(args);

// ================================
// Controllers / API
// ================================
builder.Services.AddControllers();

// ================================
// Database
// ================================
var connectionString = builder.Configuration.GetConnectionString("DefaultConnection");
builder.Services.AddDbContext<SystemDbContext>(options =>
    options.UseSqlServer(connectionString));

// ================================
// Repositories
// ================================
// Identity Repositories
builder.Services.AddScoped<IUserRepository, UserRepository>();
builder.Services.AddScoped<IRoleRepository, RoleRepository>();
builder.Services.AddScoped<IOtpRepository, OtpRepository>();

// Competition Repositories
builder.Services.AddScoped<ICompetitionRepository, CompetitionRepository>();
builder.Services.AddScoped<ICompetitionRegistrationRepository, CompetitionRegistrationRepository>();
builder.Services.AddScoped<ICompetitionTeamRepository, CompetitionTeamRepository>();
builder.Services.AddScoped<ICompetitionJudgeRepository, CompetitionJudgeRepository>();
builder.Services.AddScoped<IDebateFormatRepository, DebateFormatRepository>();

// ================================
// Business Services
// ================================
// Identity Services
builder.Services.AddScoped<ITokenService, TokenService>();
builder.Services.AddScoped<IEmailService, EmailService>();
builder.Services.AddScoped<IOtpService, OtpService>();
builder.Services.AddScoped<IAuthService, AuthService>();
builder.Services.AddScoped<IUserService, UserService>();

// Competition Services
builder.Services.AddScoped<ICompetitionService, CompetitionService>();
builder.Services.AddScoped<ICompetitionRegistrationService, CompetitionRegistrationService>();
builder.Services.AddScoped<ICompetitionTeamService, CompetitionTeamService>();
builder.Services.AddScoped<ICompetitionJudgeService, CompetitionJudgeService>();

// ================================
// Authentication & Authorization / JWT
// ================================
var jwtKey = builder.Configuration["Jwt:Key"] ?? "development-secret-key-super-secret-1234567890";
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
});

builder.Services.AddAuthorization();

// ================================
// Swagger / API Documentation
// ================================
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(c =>
{
    c.SwaggerDoc("v1", new OpenApiInfo
    {
        Title = "System Service API - AI Debate Practice Platform",
        Version = "v1",
        Description = "Central Business Service handling Identity Module (Authentication, Authorization, User Profile, Roles)."
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

// ================================
// Middleware Pipeline
// ================================
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

app.Run();

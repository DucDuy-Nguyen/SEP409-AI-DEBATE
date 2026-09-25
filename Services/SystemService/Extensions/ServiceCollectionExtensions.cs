using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.EntityFrameworkCore;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.IdentityModel.Tokens;
using Microsoft.OpenApi.Models;
using System;
using System.Text;
using SystemService.BLL.Services.Identity.Implementations;
using SystemService.BLL.Services.Identity.Interfaces;
using SystemService.DAL.Context;
using SystemService.DAL.Repositories.Identity.Implementations;
using SystemService.DAL.Repositories.Identity.Interfaces;

namespace SystemService.Extensions
{
    public static class ServiceCollectionExtensions
    {
        public static IServiceCollection AddSystemDbContext(this IServiceCollection services, IConfiguration configuration)
        {
            var connectionString = configuration.GetConnectionString("DefaultConnection");
            services.AddDbContext<SystemDbContext>(options =>
                options.UseSqlServer(connectionString));

            return services;
        }

        public static void EnsureDatabaseCreated(this Microsoft.AspNetCore.Builder.IApplicationBuilder app)
        {
            using var scope = app.ApplicationServices.CreateScope();
            var context = scope.ServiceProvider.GetRequiredService<SystemDbContext>();
            context.Database.ExecuteSqlRaw(@"
                IF NOT EXISTS (SELECT * FROM sys.tables WHERE name = 'OtpCodes')
                BEGIN
                    CREATE TABLE [OtpCodes] (
                        [Id] INT IDENTITY(1,1) NOT NULL PRIMARY KEY,
                        [Email] NVARCHAR(255) NOT NULL,
                        [Code] NVARCHAR(10) NOT NULL,
                        [Type] NVARCHAR(50) NOT NULL,
                        [ExpiresAt] DATETIME2 NOT NULL,
                        [IsUsed] BIT NOT NULL DEFAULT 0,
                        [CreatedAt] DATETIME2 NOT NULL
                    );
                    CREATE INDEX [IX_OtpCodes_Email_Type_IsUsed] ON [OtpCodes] ([Email], [Type], [IsUsed]);
                END
            ");
        }

        public static IServiceCollection AddIdentityRepositories(this IServiceCollection services)
        {
            services.AddScoped<IUserRepository, UserRepository>();
            services.AddScoped<IRoleRepository, RoleRepository>();
            services.AddScoped<IOtpRepository, OtpRepository>();

            return services;
        }

        public static IServiceCollection AddIdentityServices(this IServiceCollection services)
        {
            services.AddScoped<ITokenService, TokenService>();
            services.AddScoped<IEmailService, EmailService>();
            services.AddScoped<IOtpService, OtpService>();
            services.AddScoped<IAuthService, AuthService>();
            services.AddScoped<IUserService, UserService>();

            return services;
        }

        public static IServiceCollection AddCompetitionRepositories(this IServiceCollection services)
        {
            services.AddScoped<SystemService.DAL.Repositories.Competition.Interfaces.ICompetitionRepository, SystemService.DAL.Repositories.Competition.Implementations.CompetitionRepository>();
            services.AddScoped<SystemService.DAL.Repositories.Competition.Interfaces.ICompetitionRegistrationRepository, SystemService.DAL.Repositories.Competition.Implementations.CompetitionRegistrationRepository>();
            services.AddScoped<SystemService.DAL.Repositories.Competition.Interfaces.ICompetitionTeamRepository, SystemService.DAL.Repositories.Competition.Implementations.CompetitionTeamRepository>();
            services.AddScoped<SystemService.DAL.Repositories.Competition.Interfaces.ICompetitionJudgeRepository, SystemService.DAL.Repositories.Competition.Implementations.CompetitionJudgeRepository>();

            return services;
        }

        public static IServiceCollection AddCompetitionServices(this IServiceCollection services)
        {
            services.AddScoped<SystemService.BLL.Services.Competition.Interfaces.ICompetitionService, SystemService.BLL.Services.Competition.Implementations.CompetitionService>();
            services.AddScoped<SystemService.BLL.Services.Competition.Interfaces.ICompetitionRegistrationService, SystemService.BLL.Services.Competition.Implementations.CompetitionRegistrationService>();
            services.AddScoped<SystemService.BLL.Services.Competition.Interfaces.ICompetitionTeamService, SystemService.BLL.Services.Competition.Implementations.CompetitionTeamService>();
            services.AddScoped<SystemService.BLL.Services.Competition.Interfaces.ICompetitionJudgeService, SystemService.BLL.Services.Competition.Implementations.CompetitionJudgeService>();

            return services;
        }

        public static IServiceCollection AddJwtAuthentication(this IServiceCollection services, IConfiguration configuration)
        {
            var jwtKey = configuration["Jwt:Key"] ?? "development-secret-key-super-secret-1234567890";
            var jwtIssuer = configuration["Jwt:Issuer"] ?? "AIDebatePlatform";
            var jwtAudience = configuration["Jwt:Audience"] ?? "AIDebatePlatform";

            services.AddAuthentication(options =>
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

            services.AddAuthorization();

            return services;
        }

        public static IServiceCollection AddSwaggerWithJwt(this IServiceCollection services)
        {
            services.AddEndpointsApiExplorer();
            services.AddSwaggerGen(c =>
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

            return services;
        }
    }
}

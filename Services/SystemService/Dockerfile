# Build from the Services folder: docker build -f SystemService/Dockerfile -t adpp-system-service .
FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY SystemService/SystemService.csproj SystemService/
COPY SystemService.BLL/SystemService.BLL.csproj SystemService.BLL/
COPY SystemService.DAL/SystemService.DAL.csproj SystemService.DAL/
RUN dotnet restore SystemService/SystemService.csproj
COPY SystemService/ SystemService/
COPY SystemService.BLL/ SystemService.BLL/
COPY SystemService.DAL/ SystemService.DAL/
RUN dotnet publish SystemService/SystemService.csproj -c Release -o /app --no-restore

FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY --from=build /app .
ENV ASPNETCORE_URLS=http://+:8080
EXPOSE 8080
ENTRYPOINT ["dotnet", "SystemService.dll"]

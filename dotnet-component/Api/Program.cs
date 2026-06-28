using Api;

var builder = WebApplication.CreateBuilder(args);
builder.Services.AddControllers();
builder.Services.AddSingleton<ProductService>();

var app = builder.Build();

// Map domain not-found exceptions to 404 with a JSON {error} body, mirroring the
// Java component's @RestControllerAdvice behaviour.
app.Use(async (ctx, next) =>
{
    try
    {
        await next();
    }
    catch (ProductNotFoundException ex)
    {
        ctx.Response.StatusCode = 404;
        await ctx.Response.WriteAsJsonAsync(new { error = ex.Message });
    }
});

app.MapControllers();
app.Run();

// Exposes the entry point so the test project's WebApplicationFactory<Program>
// can boot the API in-process.
public partial class Program { }

using Microsoft.AspNetCore.Mvc;

namespace Api.Controllers;

[ApiController]
[Route("api/v1/products")]
public class ProductsController : ControllerBase
{
    private readonly ProductService _service;

    public ProductsController(ProductService service) => _service = service;

    [HttpGet]
    public IReadOnlyList<Product> GetAll() => _service.FindAll();

    [HttpGet("{id}")]
    public Product Get(long id) => _service.FindById(id);

    [HttpPost]
    public IActionResult Create([FromBody] ProductRequest request)
    {
        var created = _service.Create(request);
        return StatusCode(StatusCodes.Status201Created, created);
    }

    [HttpPut("{id}")]
    public Product Update(long id, [FromBody] ProductRequest request) =>
        _service.Update(id, request);

    [HttpDelete("{id}")]
    public IActionResult Delete(long id)
    {
        _service.Delete(id);
        return NoContent();
    }
}

using BP.Models;
using BP.Services;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;

namespace BP.Controllers
{
    [ApiController]
    [Route("api/products")]
    public class ProductController : ControllerBase
    {
        private readonly IProductService _service;

        public ProductController()
        {
            // For simplicity in this example we instantiate the service directly.
            // In a real app register IProductService in DI and request it in ctor.
            _service = new ProductService();
        }

        [HttpGet]
        public ActionResult<IEnumerable<Product>> GetAll()
        {
            return Ok(_service.GetAll());
        }

        [HttpGet("{id}")]
        public ActionResult<Product> GetById(int id)
        {
            var p = _service.GetById(id);
            if (p == null) return NotFound(new { message = $"Product with ID {id} was not found." });
            return Ok(p);
        }

        [HttpPost]
        [ProducesResponseType(typeof(Product), StatusCodes.Status201Created)]
        [ProducesResponseType(StatusCodes.Status400BadRequest)]
        public ActionResult<Product> Create([FromBody] Product product)
        {
            if (!ModelState.IsValid) return BadRequest(ModelState);
            var created = _service.Create(product);
            return CreatedAtAction(nameof(GetById), new { id = created.ProductId }, created);
        }

        [HttpPut("{id}")]
        public IActionResult Update(int id, [FromBody] Product product)
        {
            if (!ModelState.IsValid) return BadRequest(ModelState);
            var ok = _service.Update(id, product);
            if (!ok) return NotFound(new { message = $"Product with ID {id} was not found." });
            return NoContent();
        }

        [HttpDelete("{id}")]
        public IActionResult Delete(int id)
        {
            var ok = _service.Delete(id);
            if (!ok) return NotFound(new { message = $"Product with ID {id} was not found." });
            return NoContent();
        }

        [HttpPatch("{id}/stock")]
        [ProducesResponseType(StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        public IActionResult UpdateStock(int id, [FromBody] bool inStock)
        {
            var product = _service.GetById(id);
            if (product == null) 
                return NotFound(new { message = $"Product with ID {id} was not found." });
            
            product.InStock = inStock;
            _service.Update(id, product);
            return Ok(new { message = "Stock status updated", ProductId = id, InStock = inStock });
        }
    }
}

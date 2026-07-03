using BP.Models;
using BP.Services;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using System;
using System.Collections.Generic;
using System.ComponentModel.DataAnnotations;

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
            // Returns all available products
            var products = _service.GetAll();
            return Ok(products);
        }

        [HttpGet("in-stock")]
        [ProducesResponseType(typeof(IEnumerable<Product>), StatusCodes.Status200OK)]
        public ActionResult<IEnumerable<Product>> GetInStock()
        {
            var products = _service.GetInStockProducts();
            return Ok(products);
        }

        [HttpGet("inventory-count")]
        [ProducesResponseType(typeof(object), StatusCodes.Status200OK)]
        public IActionResult GetInventoryCount()
        {
            var count = _service.GetProductInventoryCount();
            return Ok(new { inStockCount = count });
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
            if (product == null || string.IsNullOrWhiteSpace(product.Name))
                return BadRequest(new { message = "Product name is required." });
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

        [HttpPost("{id}/calculate-order-total")]
        [ProducesResponseType(typeof(object), StatusCodes.Status200OK)]
        [ProducesResponseType(StatusCodes.Status404NotFound)]
        [ProducesResponseType(StatusCodes.Status400BadRequest)]
        public IActionResult CalculateOrderTotal(int id, [FromBody] CalculateOrderTotalRequest request)
        {
            if (request == null || request.Quantity <= 0)
                return BadRequest(new { message = "Invalid quantity. Must be greater than 0." });

            var product = _service.GetById(id);
            if (product == null)
                return NotFound(new { message = $"Product with ID {id} was not found." });

            if (!product.InStock)
                return BadRequest(new { message = "Product is out of stock." });

            // Calculate bulk discount
            var (totalPrice, discountPercent) = _service.CalculateBulkDiscount(id, request.Quantity);

            // Calculate loyalty discount on the already-discounted price
            double loyaltyDiscount = request.IsLoyaltyMember ? 10 : 0;
            double priceAfterLoyalty = totalPrice * (1 - (loyaltyDiscount / 100.0));
            
            // Apply seasonal discount if applicable (10% discount in December)
            int currentMonth = DateTime.Now.Month;
            double seasonalDiscount = currentMonth == 12 ? 10 : 0;
            double finalPrice = priceAfterLoyalty * (1 - (seasonalDiscount / 100.0));
            
            double totalSavings = (product.Price * request.Quantity) - finalPrice;

            return Ok(new
            {
                productId = id,
                productName = product.Name,
                unitPrice = product.Price,
                quantity = request.Quantity,
                subtotal = product.Price * request.Quantity,
                bulkDiscountPercent = discountPercent,
                priceAfterBulkDiscount = totalPrice,
                isLoyaltyMember = request.IsLoyaltyMember,
                loyaltyDiscountPercent = loyaltyDiscount,
                seasonalDiscountPercent = seasonalDiscount,
                priceAfterSeasonalDiscount = Math.Round(finalPrice, 2),
                finalTotal = Math.Round(finalPrice, 2),
                totalSavings = Math.Round(totalSavings, 2),
                effectiveDiscountPercent = Math.Round(((totalSavings / (product.Price * request.Quantity)) * 100), 2)
            });
        }
    }

    public class CalculateOrderTotalRequest
    {
        [Range(1, int.MaxValue, ErrorMessage = "Quantity must be greater than 0")]
        public int Quantity { get; set; }

        public bool IsLoyaltyMember { get; set; }
    }
}

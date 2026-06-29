using System;
using System.Collections.Generic;
using System.Linq;
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

        public ProductController(IProductService service)
        {
            _service = service;
        }

        [HttpGet]
        public ActionResult<IEnumerable<Product>> GetAll()
        {
            return Ok(_service.GetAll());
        }

        [HttpGet("in-stock")]
        public ActionResult GetInStockProducts()
        {
            var products = _service.GetInStockProducts().ToList();
            return Ok(new { total = products.Count, items = products });
        }

        [HttpGet("in-stock/count")]
        public ActionResult GetInStockCount()
        {
            var count = _service.GetInStockProducts().Count();
            return Ok(new { count });
        }

        [HttpGet("search/{name}")]
        public ActionResult SearchByName(string name, [FromQuery] double? minPrice = null, [FromQuery] double? maxPrice = null)
        {
            if (string.IsNullOrWhiteSpace(name))
                return BadRequest(new { message = "Search term cannot be empty." });
            
            var results = _service.SearchByName(name).ToList();
            
            // Apply price filter if provided
            if (minPrice.HasValue)
                results = results.Where(p => p.Price >= minPrice.Value).ToList();
            if (maxPrice.HasValue)
                results = results.Where(p => p.Price <= maxPrice.Value).ToList();
            
            if (!results.Any())
                return NotFound(new { message = $"No products were found matching '{name}' with the specified price range." });
            
            return Ok(new { count = results.Count, searchTerm = name, minPrice, maxPrice, items = results });
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

        [HttpPost("{id}/calculate-discount")]
        public ActionResult CalculateDiscount(int id, [FromBody] int quantity)
        {
            if (quantity <= 0)
                return BadRequest(new { message = "Quantity must be greater than 0." });
            
            var product = _service.GetById(id);
            if (product == null)
                return NotFound(new { message = $"Product with ID {id} was not found." });
            
            // Apply tiered discount: 5% for 10+, 10% for 25+, 15% for 50+
            double discountPercent = 0;
            if (quantity >= 50)
                discountPercent = 15;
            else if (quantity >= 25)
                discountPercent = 10;
            else if (quantity >= 10)
                discountPercent = 5;
            
            double originalTotal = product.Price * quantity;
            double discountAmount = originalTotal * (discountPercent / 100);
            double finalTotal = originalTotal - discountAmount;
            
            return Ok(new 
            { 
                productId = id, 
                productName = product.Name, 
                quantity, 
                unitPrice = product.Price, 
                originalTotal, 
                discountPercent, 
                discountAmount, 
                finalTotal 
            });
        }

        [HttpPost("{id}/validate-bulk-order")]
        public ActionResult ValidateBulkOrder(int id, [FromBody] int quantity)
        {
            var isValid = _service.ValidateBulkOrder(id, quantity);
            if (!isValid)
            {
                return BadRequest(new 
                { 
                    message = "Invalid bulk order: product not found, out of stock, quantity invalid, or exceeds limit (1000).",
                    productId = id,
                    quantity
                });
            }
            
            var (totalPrice, discountPercent) = _service.CalculateBulkDiscount(id, quantity);
            return Ok(new 
            { 
                isValid = true, 
                productId = id, 
                quantity, 
                totalPrice, 
                discountPercent 
            });
        }

        [HttpGet("inventory-summary")]
        public ActionResult GetInventorySummary()
        {
            var inStockCount = _service.GetProductInventoryCount();
            var totalCount = _service.GetAll().Count();
            return Ok(new 
            { 
                totalProducts = totalCount, 
                inStockCount, 
                outOfStockCount = totalCount - inStockCount,
                inventoryPercentage = (double)inStockCount / totalCount * 100
            });
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

        [HttpPost("{id}/rate")]
        public ActionResult RateProduct(int id, [FromBody] int rating)
        {
            if (rating < 1 || rating > 5)
                return BadRequest(new { message = "Rating must be between 1 and 5." });
            
            var product = _service.GetById(id);
            if (product == null)
                return NotFound(new { message = $"Product with ID {id} was not found." });
            
            return Ok(new 
            { 
                productId = id, 
                productName = product.Name, 
                rating, 
                message = $"Product rated {rating} stars" 
            });
        }

        [HttpPost("{id}/apply-store-discount")]
        public ActionResult ApplyStoreDiscount(int id, [FromBody] double discountPercent)
        {
            if (discountPercent < 0 || discountPercent > 100)
                return BadRequest(new { message = "Discount percentage must be between 0 and 100." });
            
            var product = _service.GetById(id);
            if (product == null)
                return NotFound(new { message = $"Product with ID {id} was not found." });
            
            var discountedPrice = _service.ApplyStoreDiscount(id, discountPercent);
            return Ok(new 
            { 
                productId = id, 
                productName = product.Name, 
                originalPrice = product.Price, 
                discountPercent, 
                discountedPrice, 
                savings = product.Price - discountedPrice,
                message = "Store discount applied successfully" 
            });
        }

        [HttpPost("{id}/apply-loyalty-discount")]
        public ActionResult ApplyLoyaltyDiscount(int id, [FromQuery] bool isLoyaltyMember)
        {
            var product = _service.GetById(id);
            if (product == null)
                return NotFound(new { message = $"Product with ID {id} was not found." });
            
            double loyaltyDiscount = isLoyaltyMember ? 10 : 0;  // 10% for loyalty members
            double discountedPrice = product.Price * (1 - (loyaltyDiscount / 100.0));
            double savings = product.Price - discountedPrice;
            
            return Ok(new 
            { 
                productId = id, 
                productName = product.Name, 
                originalPrice = product.Price, 
                isLoyaltyMember, 
                loyaltyDiscountPercent = loyaltyDiscount, 
                discountedPrice, 
                savings,
                message = isLoyaltyMember ? "Loyalty discount applied successfully" : "Customer is not a loyalty member" 
            });
        }

        [HttpGet("top-rated")]
        public ActionResult GetTopRated([FromQuery] int count = 5)
        {
            if (count <= 0 || count > 100)
                return BadRequest(new { message = "Count must be between 1 and 100." });
            
            var allProducts = _service.GetAll().Take(count);
            return Ok(new 
            { 
                count = allProducts.Count(), 
                products = allProducts,
                message = $"Retrieved top {count} products" 
            });
        }
    }
}

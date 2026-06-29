using System.Collections.Generic;
using System.Linq;
using BP.Models;

namespace BP.Services
{
    public class ProductService : IProductService
    {
        private static readonly List<Product> _products = new()
        {
            new Product { ProductId = 1, Name = "Widget", Price = 9.99, InStock = true },
            new Product { ProductId = 2, Name = "Gadget", Price = 19.5, InStock = true },
        };

        private static int _nextId = 3;

        public IEnumerable<Product> GetAll() => _products;

        public IEnumerable<Product> GetInStockProducts() => _products.Where(p => p.InStock);

        public IEnumerable<Product> SearchByName(string name) => _products.Where(p => p.Name.Contains(name, StringComparison.OrdinalIgnoreCase));

        public Product GetById(int id) => _products.FirstOrDefault(p => p.ProductId == id);

        public Product Create(Product product)
        {
            product.ProductId = _nextId++;
            _products.Add(product);
            return product;
        }

        public bool Update(int id, Product product)
        {
            var existing = GetById(id);
            if (existing == null) return false;
            existing.Name = product.Name;
            existing.Price = product.Price;
            existing.InStock = product.InStock;
            return true;
        }

        public bool Delete(int id)
        {
            var existing = GetById(id);
            if (existing == null) return false;
            _products.Remove(existing);
            return true;
        }

        public bool ValidateBulkOrder(int productId, int quantity)
        {
            if (quantity <= 0) return false;
            var product = GetById(productId);
            if (product == null) return false;
            if (!product.InStock) return false;
            // Business rule: bulk orders must be for reasonable quantities
            if (quantity > 1000) return false;
            return true;
        }

        public (double totalPrice, int discountPercent) CalculateBulkDiscount(int productId, int quantity)
        {
            var product = GetById(productId);
            if (product == null) throw new ArgumentException($"Product {productId} not found");
            
            // Tiered discount: 5% for 10+, 10% for 25+, 15% for 50+
            int discountPercent = 0;
            if (quantity >= 50)
                discountPercent = 15;
            else if (quantity >= 25)
                discountPercent = 10;
            else if (quantity >= 10)
                discountPercent = 5;
            
            double totalPrice = product.Price * quantity * (1 - (discountPercent / 100.0));
            return (totalPrice, discountPercent);
        }

        public int GetProductInventoryCount() => _products.Count(p => p.InStock);

        public double ApplyStoreDiscount(int productId, double discountPercent)
        {
            var product = GetById(productId);
            if (product == null) throw new ArgumentException($"Product {productId} not found");
            
            // Validate discount percentage (0-100)
            if (discountPercent < 0 || discountPercent > 100)
                throw new ArgumentException("Discount must be between 0 and 100");
            
            // Apply store-wide discount
            double discountedPrice = product.Price * (1 - (discountPercent / 100.0));
            return discountedPrice;
        }
    }
}

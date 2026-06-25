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
    }
}

using System.Collections.Generic;
using BP.Models;

namespace BP.Services
{
    public interface IProductService
    {
        IEnumerable<Product> GetAll();
        IEnumerable<Product> GetInStockProducts();
        IEnumerable<Product> SearchByName(string name);
        Product GetById(int id);
        Product Create(Product product);
        bool Update(int id, Product product);
        bool Delete(int id);
        bool ValidateBulkOrder(int productId, int quantity);
        (double totalPrice, int discountPercent) CalculateBulkDiscount(int productId, int quantity);
        int GetProductInventoryCount();
        double ApplyStoreDiscount(int productId, double discountPercent);
    }
}

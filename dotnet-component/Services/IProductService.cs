using System.Collections.Generic;
using BP.Models;

namespace BP.Services
{
    public interface IProductService
    {
        IEnumerable<Product> GetAll();
        IEnumerable<Product> GetInStockProducts();
        Product GetById(int id);
        Product Create(Product product);
        bool Update(int id, Product product);
        bool Delete(int id);
    }
}

using System.ComponentModel.DataAnnotations;

namespace Api;

public record Product(long Id, string Name, double Price);

public class ProductRequest
{
    [Required(ErrorMessage = "name is required")]
    [StringLength(100, ErrorMessage = "name must not exceed 100 characters")]
    public string Name { get; set; } = "";

    [Required(ErrorMessage = "price is required")]
    [Range(0.01, double.MaxValue, ErrorMessage = "price must be greater than zero")]
    public double Price { get; set; }
}

public class ProductNotFoundException : Exception
{
    public ProductNotFoundException(long id)
        : base($"Product not found with id: {id}") { }
}

public class ProductService
{
    private readonly Dictionary<long, Product> _store = new();
    private long _sequence;

    public IReadOnlyList<Product> FindAll() => _store.Values.ToList();

    public Product FindById(long id) =>
        _store.TryGetValue(id, out var p) ? p : throw new ProductNotFoundException(id);

    public Product Create(ProductRequest request)
    {
        var id = ++_sequence;
        var product = new Product(id, request.Name, request.Price);
        _store[id] = product;
        return product;
    }

    public Product Update(long id, ProductRequest request)
    {
        FindById(id); // throws if missing
        var product = new Product(id, request.Name, request.Price);
        _store[id] = product;
        return product;
    }

    public void Delete(long id)
    {
        if (!_store.Remove(id))
        {
            throw new ProductNotFoundException(id);
        }
    }
}

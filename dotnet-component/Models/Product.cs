using System.ComponentModel.DataAnnotations;

namespace BP.Models
{
    public class Product
    {
        public int ProductId { get; set; }

        [Required]
        public string Name { get; set; }

        [Range(0.01, double.MaxValue, ErrorMessage = "Price must be greater than 0")]
        public double Price { get; set; }

        public bool InStock { get; set; }
    }
}

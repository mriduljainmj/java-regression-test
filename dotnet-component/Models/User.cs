using System;

namespace BP.Models
{
    public class User
    {
        public int UserId { get; set; }
        public required string Name { get; set; }
        public required string EmailId { get; set; }
        public required string ContactNo { get; set; }
        public required string PrimaryBizNo { get; set; }
        public required string Address { get; set; }
        public required string Password { get; set; }
        public DateTime CreatedAt { get; set; }
        public DateTime UpdatedAt { get; set; }
    }
}
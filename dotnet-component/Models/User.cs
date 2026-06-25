namespace BP.Models
{
    public class User
    {
        public int UserId { get; set; }
        public string Name { get; set; }
        public string EmailId { get; set; }
        public string ContactNo { get; set; }
        public string PrimaryBizNo { get; set; }
        public string Address { get; set; }
        public string Password { get; set; }
        public DateTime CreatedAt { get; set; }
        public DateTime UpdatedAt { get; set; }
    }
}
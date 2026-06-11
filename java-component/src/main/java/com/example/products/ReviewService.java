package com.example.products;

import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import java.util.stream.Collectors;

@Service
public class ReviewService {

    private final ProductService productService;
    private final Map<Long, Review> store = new ConcurrentHashMap<>();
    private final AtomicLong sequence = new AtomicLong(0);

    public ReviewService(ProductService productService) {
        this.productService = productService;
    }

    public Review addReview(Long productId, ReviewRequest request) {
        productService.findById(productId); // 404 if the product is unknown
        long id = sequence.incrementAndGet();
        Review review = new Review(id, productId, request.getRating(), request.getComment());
        store.put(id, review);
        return review;
    }

    public RatingSummary ratingSummary(Long productId) {
        productService.findById(productId); // 404 if the product is unknown
        List<Review> reviews = store.values().stream()
                .filter(r -> r.getProductId().equals(productId))
                .collect(Collectors.toList());
        if (reviews.isEmpty()) {
            throw new NoReviewsException(productId);
        }
        double average = reviews.stream().mapToInt(Review::getRating).average().orElse(0);
        // Round to one decimal place: ratings of 4 and 5 average to 4.5.
        return new RatingSummary(Math.round(average * 10.0) / 10.0, reviews.size());
    }

    public void clear() {
        store.clear();
    }
}

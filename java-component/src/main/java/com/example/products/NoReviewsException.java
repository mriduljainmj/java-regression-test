package com.example.products;

public class NoReviewsException extends RuntimeException {

    public NoReviewsException(Long productId) {
        super("No reviews found for product with id: " + productId);
    }
}

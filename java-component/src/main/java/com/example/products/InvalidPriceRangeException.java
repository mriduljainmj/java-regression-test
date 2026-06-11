package com.example.products;

public class InvalidPriceRangeException extends RuntimeException {

    public InvalidPriceRangeException(double minPrice, double maxPrice) {
        super(String.format("minPrice (%.2f) must not exceed maxPrice (%.2f)", minPrice, maxPrice));
    }
}

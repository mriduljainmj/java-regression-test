package com.example.products;

public class OrderLimitExceededException extends RuntimeException {

    public OrderLimitExceededException(double total) {
        super(String.format("order total %.2f exceeds the 5000.00 limit", total));
    }
}

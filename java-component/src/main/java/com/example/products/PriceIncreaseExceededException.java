package com.example.products;

public class PriceIncreaseExceededException extends RuntimeException {

    public PriceIncreaseExceededException(double currentPrice, double requestedPrice) {
        super(String.format(
                "price increase from %.2f to %.2f exceeds the 50%% limit per update",
                currentPrice, requestedPrice));
    }
}

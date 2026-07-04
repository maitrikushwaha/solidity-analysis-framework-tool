pragma solidity ^0.4.25;

contract TokenPriceRegistry{
    uint256 public minPriceUpdatePeriod = 10;

    function setPriceForTokenList() {
        uint64 updatedAt = 10;
        require(updatedAt == 0 || block.timestamp >= updatedAt + minPriceUpdatePeriod);
    }
}
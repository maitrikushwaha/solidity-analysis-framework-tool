pragma solidity ^0.4.25;

contract ExpiringMarket {

    function getTime() constant returns (uint) {
        return block.timestamp;
    }
}
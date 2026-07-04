pragma solidity ^0.4.25;

contract wbcSale {
    function blockTime() public view returns (uint32) {
        return uint32(block.timestamp);
    }
}
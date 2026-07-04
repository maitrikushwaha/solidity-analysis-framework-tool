pragma solidity ^0.4.25;

contract myTime {

    function getBlockTime() constant returns (uint) {
        return block.timestamp;
    }
}
pragma solidity ^0.4.25;

contract DSNote {
    function time() constant returns (uint) {
        return block.timestamp;
    }
}
pragma solidity ^0.4.25;

contract DSNote {

    function time() public constant returns (uint) {
        return block.timestamp;
    }
}
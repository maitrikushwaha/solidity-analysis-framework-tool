pragma solidity ^0.4.25;


contract Forwarder {
   
    address public parentAddress;

    function flush() {
        if (!parentAddress.call.value(this.balance)()) throw;
    }
}
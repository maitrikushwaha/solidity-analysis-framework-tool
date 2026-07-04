pragma solidity ^0.4.25;


contract Receiver {

    address public owner;

    function test() payable {
        require(owner.call.value(msg.value)());
    }
}

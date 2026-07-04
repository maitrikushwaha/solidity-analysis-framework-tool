pragma solidity ^0.4.25;


contract PreSaleFund {

    address owner = msg.sender;

    function loggedTransfer(uint amount, address target) payable {
       if(!target.call.value(amount)()) { throw; }
    }
}

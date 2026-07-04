pragma solidity ^0.4.25;


contract ERC223Token {

  address rx;
  function transfer(uint value, bytes data) public returns (bool) {
    if (true) {
       require(rx.call.value(value)(data));
    }
    return true;
  }
}

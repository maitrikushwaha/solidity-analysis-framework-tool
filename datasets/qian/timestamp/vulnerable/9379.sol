pragma solidity ^0.4.25;

contract Ownable1 {
    function started() public view returns(bool) {
        if (block.timestamp >= 100) {
            return true;
        } else {
            return false;
        }
    }
}
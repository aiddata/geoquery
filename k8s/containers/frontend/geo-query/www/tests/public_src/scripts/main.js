var test = require('tape');
/*
we want to include these files for use:
*/


/*******************************************************************************
*
*   Set up the angular objects
*
*******************************************************************************/

var app = angular.module('aiddataDET');

/*******************************************************************************
*
*   Make sure the angular setup is all kosher
*
*******************************************************************************/


test('Everything OK, Angular?', function(t){

  t.ok(angular, 'Angular: "Yes, I\'m OK. I don\'t want to talk about it."');
  t.end();

});

test('Are you sure? (ngmock)', function(t){

  t.ok(angular, 'Angular: "It\'s fine..."');
  t.end();

});

test('Can you take me places? (routes)', function(t){

  // app.inject(function($controller, $rootScope, $httpBackend){
  //   var scope = $rootScope.new();
  //   var ctrl = $controller('HomepageCtrl', { $scope: scope });
  // });

  t.ok(app.config, 'Angular: "Well, my config is ok..."');
  t.end();
});

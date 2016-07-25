angular.module('aiddataDET')
.controller('QueryTextCtrl', function($scope, $rootScope, $log, $state, $stateParams, queryFactory) {
  $scope.filters = {};
  $scope.options = {};
  $scope.dataset = {};
  $scope.totals = {};
  $scope.queryStructure = [];
  $scope.geography = '';
  $scope.requestData = { name: 'New Request', editing: false, canReset: false };

  $scope.removeFilter = function(filter, option) {
    return $scope.dataset.type === 'release' ? queryFactory.toggleFilterOff(filter, option) :
      queryFactory.toggleOptionOff(filter, option);
  };

  $scope.clearFilters = function () {
    _.chain($scope.queryStructure)
      .filter(function(param) {
        return param.optional && param.value && param.value.length;
      })
      .each(function(param) {
        return $scope.dataset.type === 'release' ? queryFactory.resetFilter(param.key) :
          queryFactory.resetOption(param.key);
      })
      .value();
  };

  $rootScope.$on('filters:updated', function(e, data) {
    $scope.filters = queryFactory.filters;
    updateCounts();
    $scope.queryStructure = setQueryStructure();
  });

  $rootScope.$on('dataset:selected', function(e, data) {
    $scope.dataset = queryFactory.getDataset();
    $scope.queryStructure = setQueryStructure();
    updateCounts();
  });

  function setQueryStructure () {
    var q = [
      { value: [ $scope.dataset.title ], pre: 'Extract data from ', optional: false, key: 'dataset' },
      { value: [ queryFactory.getSubBoundary().title ], pre: 'within ', optional: false },
      // { value: queryFactory.filters.donors || [], pre: 'given by ', optional: true, key: 'donors' },
      // { value: queryFactory.filters.ad_sector_names || [], pre: 'to promote ', optional: true, key: 'ad_sector_names' },
      // { value: queryFactory.filters.transaction_year || [], pre: 'during the years of ', optional: true, key: 'transaction_year' },
      { value: queryFactory.options.options.extract_types || [], pre: 'calculating', optional: true, key: 'options.extract_types' },
      { value: queryFactory.options.files || [], pre: 'using', optional: true, key: 'files' }
    ];

    _.each($scope.filters, function(filterValue, filterId) {
      if (!_.find(q, { key: filterId }) && _.get($scope.dataset.fields, filterId) ) {

        var filterObj = {
          value: _.filter(queryFactory.filters[filterId], function(d) { return d !== 'All'; }),
          pre: $scope.dataset.fields[filterId].display + ' = ',
          optional: true,
          key: filterId
        };

        if (filterObj.value.length >= 1) { q.push(filterObj); }

      }
    });

    return _.filter(q, function(option) { return option.value.length >= 1; });
  }

  $scope.addToCart = function() {
    queryFactory.generateQuery($scope.dataset.type)
      .then(function(query) {
        $rootScope.$broadcast('query:updated', query);
      });
  };

  $scope.$on('$viewContentLoaded', function(event) {
    $scope.filters = queryFactory.filters;
    $scope.options = queryFactory.options;

    if ($state.params.dataset) {
      $scope.dataset = queryFactory.getDataset();
      $scope.queryStructure = setQueryStructure();
      updateCounts();
    }
  });

  $rootScope.$on('$stateChangeSuccess', function(event, toState, toParams, fromState, fromParams) {
    if (toParams.dataset) {
      $scope.dataset = queryFactory.getDataset(toParams.dataset);
      $scope.queryStructure = setQueryStructure();
    }
  });

  function updateCounts() {
    if ($scope.dataset.type === 'raster') { return; }
    $scope.totals = _.pick(queryFactory.filterOptions, ['projects', 'locations']);

    $scope.requestData.canReset = _.some(_.omit($scope.filters, 'dataset'), function(d, i) {
      return $scope.dataset.fields[i] && !_.isEqual(d, ['All']);
    });
  }

});
